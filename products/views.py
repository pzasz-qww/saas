from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from accounts.permissions import (
    can_adjust_stock,
    can_create_stock_entry,
    can_view_stock,
    get_user_company,
)

from .models import Product, StockEntry, StockMovement, Unit


def parse_decimal(value):
    if value is None:
        return None

    value = str(value).strip().replace(",", ".")

    if value == "":
        return None

    try:
        return Decimal(value)
    except InvalidOperation:
        return None


@login_required
def stock_dashboard(request):
    if not can_view_stock(request.user):
        messages.warning(request, "Você não tem permissão para ver o estoque.")
        return redirect("orders:pdv")

    company = get_user_company(request.user)

    products = (
        Product.objects
        .filter(company=company, active=True)
        .select_related("company", "unit")
        .order_by("category", "name")
    )

    return render(
        request,
        "products/stock_dashboard.html",
        {
            "products": products,
            "can_create_stock_entry": can_create_stock_entry(request.user),
            "can_adjust_stock": can_adjust_stock(request.user),
        },
    )


@login_required
def product_create(request):
    if not can_create_stock_entry(request.user):
        messages.warning(request, "Você não tem permissão para cadastrar produtos.")
        return redirect("products:stock_dashboard")

    company = get_user_company(request.user)

    units = Unit.objects.filter(company=company).order_by("name")

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        category = request.POST.get("category", "").strip()
        product_type = request.POST.get("product_type", "sale")
        unit_id = request.POST.get("unit")
        sale_price = parse_decimal(request.POST.get("sale_price"))
        minimum_quantity = parse_decimal(request.POST.get("minimum_quantity"))
        active = request.POST.get("active") == "on"

        if not name:
            messages.warning(request, "Informe o nome do produto.")
            return redirect("products:product_create")

        if sale_price is None or sale_price < 0:
            messages.warning(request, "Informe um preço de venda válido.")
            return redirect("products:product_create")

        if minimum_quantity is None or minimum_quantity < 0:
            minimum_quantity = Decimal("0.00")

        unit = get_object_or_404(Unit, id=unit_id, company=company)

        Product.objects.create(
            company=company,
            name=name,
            category=category,
            product_type=product_type,
            unit=unit,
            sale_price=sale_price,
            minimum_quantity=minimum_quantity,
            active=active,
        )

        messages.success(request, f"Produto cadastrado: {name}.")
        return redirect("products:stock_dashboard")

    return render(
        request,
        "products/product_form.html",
        {
            "units": units,
            "product_types": Product.PRODUCT_TYPES,
        },
    )


@login_required
def stock_entry_create(request):
    if not can_create_stock_entry(request.user):
        messages.warning(request, "Você não tem permissão para inserir estoque.")
        return redirect("products:stock_dashboard")

    company = get_user_company(request.user)

    products = (
        Product.objects
        .filter(company=company, active=True)
        .select_related("unit")
        .order_by("category", "name")
    )

    if request.method == "POST":
        product_id = request.POST.get("product")
        entry_mode = request.POST.get("entry_mode", "simple")

        total_cost = parse_decimal(request.POST.get("total_cost"))
        quantity_added = parse_decimal(request.POST.get("quantity_added"))

        package_quantity = parse_decimal(request.POST.get("package_quantity"))
        package_cost = parse_decimal(request.POST.get("package_cost"))

        notes = request.POST.get("notes", "").strip()

        product = get_object_or_404(
            Product,
            id=product_id,
            company=company,
            active=True,
        )

        if quantity_added is None or quantity_added <= 0:
            messages.warning(request, "Informe uma quantidade gerada válida.")
            return redirect("products:stock_entry_create")

        if entry_mode == "simple":
            if total_cost is None or total_cost < 0:
                messages.warning(request, "Informe um valor investido válido.")
                return redirect("products:stock_entry_create")

        if entry_mode == "detailed":
            if package_quantity is None or package_quantity <= 0:
                messages.warning(request, "Informe a quantidade de pacotes/caixas.")
                return redirect("products:stock_entry_create")

            if package_cost is None or package_cost < 0:
                messages.warning(request, "Informe o valor por pacote/caixa.")
                return redirect("products:stock_entry_create")

            total_cost = package_quantity * package_cost

        StockEntry.objects.create(
            company=company,
            product=product,
            entry_mode=entry_mode,
            total_cost=total_cost,
            quantity_added=quantity_added,
            package_quantity=package_quantity,
            package_cost=package_cost,
            notes=notes,
            created_by=request.user,
        )

        messages.success(
            request,
            f"Entrada criada: {product.name} recebeu {quantity_added} {product.unit}.",
        )

        return redirect("products:stock_dashboard")

    return render(
        request,
        "products/stock_entry_form.html",
        {
            "products": products,
        },
    )


@login_required
def stock_count_adjust(request):
    if not can_adjust_stock(request.user):
        messages.warning(request, "Você não tem permissão para fazer conferência de estoque.")
        return redirect("products:stock_dashboard")

    company = get_user_company(request.user)

    products = (
        Product.objects
        .filter(company=company, active=True)
        .select_related("unit")
        .order_by("category", "name")
    )

    if request.method == "POST":
        product_id = request.POST.get("product")
        real_quantity = parse_decimal(request.POST.get("real_quantity"))
        notes = request.POST.get("notes", "").strip()

        product = get_object_or_404(
            Product,
            id=product_id,
            company=company,
            active=True,
        )

        if real_quantity is None or real_quantity < 0:
            messages.warning(request, "Informe uma contagem real válida.")
            return redirect("products:stock_count_adjust")

        expected_quantity = product.current_stock
        difference = real_quantity - expected_quantity

        StockMovement.objects.create(
            company=company,
            product=product,
            movement_type="stock_count",
            quantity=real_quantity,
            sale_value=Decimal("0.00"),
            cost_value=real_quantity * product.average_cost,
            reason="Conferência de estoque",
            notes=(
                f"Estoque esperado: {expected_quantity}. "
                f"Contagem real: {real_quantity}. "
                f"Diferença: {difference}. "
                f"{notes}"
            ),
            created_by=request.user,
        )

        if difference == 0:
            messages.success(
                request,
                f"Conferência registrada para {product.name}. Sem diferença no estoque.",
            )
            return redirect("products:stock_dashboard")

        if difference > 0:
            StockMovement.objects.create(
                company=company,
                product=product,
                movement_type="adjustment_positive",
                quantity=difference,
                sale_value=Decimal("0.00"),
                cost_value=difference * product.average_cost,
                reason="Ajuste positivo por conferência",
                notes=notes,
                created_by=request.user,
            )

            messages.success(
                request,
                f"{product.name}: ajuste positivo de {difference} {product.unit} aplicado.",
            )

            return redirect("products:stock_dashboard")

        quantity_to_remove = abs(difference)
        remaining_to_remove = quantity_to_remove

        entries = (
            StockEntry.objects
            .filter(
                company=company,
                product=product,
                remaining_quantity__gt=0,
            )
            .order_by("created_at")
        )

        for entry in entries:
            if remaining_to_remove <= 0:
                break

            quantity_from_entry = min(entry.remaining_quantity, remaining_to_remove)

            StockMovement.objects.create(
                company=company,
                product=product,
                stock_entry=entry,
                movement_type="adjustment_negative",
                quantity=quantity_from_entry,
                sale_value=Decimal("0.00"),
                cost_value=quantity_from_entry * entry.unit_cost,
                reason="Ajuste negativo por conferência",
                notes=notes,
                created_by=request.user,
            )

            remaining_to_remove -= quantity_from_entry

        messages.warning(
            request,
            f"{product.name}: ajuste negativo de {quantity_to_remove} {product.unit} aplicado.",
        )

        return redirect("products:stock_dashboard")

    return render(
        request,
        "products/stock_count_form.html",
        {
            "products": products,
        },
    )