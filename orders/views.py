import json
from collections import defaultdict
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.permissions import (
    can_access_pdv,
    can_approve_order,
    can_cancel_paid_order,
    can_cancel_pre_sale,
    can_create_order,
    can_discard_paid_order,
    can_mark_delivered,
    can_view_orders_panel,
    company_required,
)
from products.models import Product
from products.presentation import friendly_recipe_error
from products.recipe_services import (
    RecipeServiceError,
    build_sale_consumption_plan,
    get_products_availability,
)
from products.sale_quantities import (
    PhysicalSaleQuantityError,
    get_sale_availability,
)
from products.services import (
    InsufficientStock,
    StockServiceError,
    UntraceableSaleStock,
    get_stock_shortages,
)
from sales.models import Sale
from .models import Order, OrderItem
from .services import (
    OrderServiceError,
    approve_order as approve_order_service,
    cancel_pre_sale_order as cancel_pre_sale_order_service,
    cancel_paid_order_with_stock_return as cancel_paid_order_with_stock_return_service,
    discard_paid_order as discard_paid_order_service,
    mark_order_delivered as mark_order_delivered_service,
)


SALEABLE_PRODUCT_TYPES = ("sale", "both")
INVALID_CART_MESSAGE = (
    "Não foi possível enviar a pré-venda. "
    "Confira os itens do carrinho e tente novamente."
)
PDV_DRAFT_SESSION_KEY = "pdv_pre_sale_draft"


def format_stock_quantity(value):
    return format(value.normalize(), "f")


def build_stock_shortage_message(
    shortages,
    products_by_id,
    requested_quantities=None,
    consumption_plan=None,
):
    details = []

    for shortage in shortages:
        component_lines = []
        if consumption_plan is not None:
            component_lines = [
                (line.product, component)
                for line in consumption_plan.lines
                for component in line.components
                if component.ingredient.pk == shortage.product_id
            ]
        if component_lines:
            ingredient = consumption_plan.requirement_products[
                shortage.product_id
            ]
            prepared_names = ", ".join(
                sorted({product.name for product, _component in component_lines})
            )
            base_unit = consumption_plan.requirement_base_units[
                shortage.product_id
            ]
            if shortage.available <= 0:
                detail = (
                    f"A disponibilidade de {prepared_names} mudou. "
                    f"Ingrediente {ingredient.name}: sem estoque."
                )
            else:
                detail = (
                    f"A disponibilidade de {prepared_names} mudou. "
                    f"Ingrediente {ingredient.name}: necessários "
                    f"{format_stock_quantity(shortage.requested)} {base_unit}, disponíveis "
                    f"{format_stock_quantity(shortage.available)} {base_unit}."
                )
            details.append(detail)
            continue

        product = products_by_id[shortage.product_id]
        requested = (
            requested_quantities[shortage.product_id]
            if requested_quantities is not None
            else shortage.requested
        )
        try:
            available = get_sale_availability(
                product,
                shortage.available,
            ).available_sale_quantity
        except PhysicalSaleQuantityError:
            available = shortage.available
        sale_unit_labels = {
            "dose": ("dose", "doses"),
            "portion": ("porção", "porções"),
        }.get(product.sale_form, ("unidade", "unidades"))
        sale_unit_label = (
            sale_unit_labels[0]
            if requested == Decimal("1")
            else sale_unit_labels[1]
        )
        if shortage.available <= 0:
            detail = (
                f"A quantidade disponível de {product.name} mudou. "
                f"Disponível agora: 0 (sem estoque). "
                f"Solicitado: {format_stock_quantity(requested)} {sale_unit_label}."
            )
        else:
            detail = (
                f"A quantidade disponível de {product.name} mudou. "
                f"Disponível agora: {format_stock_quantity(available)}. "
                f"Solicitado: {format_stock_quantity(requested)} {sale_unit_label}."
            )
        details.append(detail)

    if len(details) == 1:
        return f"Não foi possível enviar a pré-venda. {details[0]}"

    formatted_details = "\n".join(f"- {detail}" for detail in details)
    return f"Não foi possível enviar a pré-venda:\n{formatted_details}"


def parse_positive_integer(value):
    if isinstance(value, bool) or value is None:
        return None

    if isinstance(value, int):
        parsed_value = value
    elif isinstance(value, str):
        value = value.strip()

        if not value.isdecimal():
            return None

        parsed_value = int(value)
    else:
        return None

    if parsed_value <= 0:
        return None

    return parsed_value


def build_approval_shortage_message(*, order, company, shortage):
    items = list(order.items.select_related("product").order_by("product_id", "id"))
    requested_quantities = defaultdict(lambda: Decimal("0.00"))
    products_by_id = {}
    for item in items:
        requested_quantities[item.product_id] += item.quantity
        products_by_id[item.product_id] = item.product

    try:
        consumption_plan = build_sale_consumption_plan(
            items=items,
            company=company,
        )
    except (RecipeServiceError, PhysicalSaleQuantityError, StockServiceError):
        return (
            "A disponibilidade mudou antes da aprovação. "
            "Revise o pedido e tente novamente."
        )

    return build_stock_shortage_message(
        [shortage],
        products_by_id,
        requested_quantities,
        consumption_plan,
    )


def order_items_for_company(company):
    return (
        OrderItem.objects
        .filter(
            company=company,
            product__company=company,
        )
        .select_related("product")
    )


@login_required
@company_required
def pdv_view(request):
    company = request.current_company

    if not can_access_pdv(request.user):
        messages.warning(request, "Você não tem permissão para acessar o PDV.")
        return redirect("/admin/")

    if request.method == "POST":
        if not can_create_order(request.user):
            messages.warning(request, "Você não tem permissão para criar pedidos.")
            return redirect("orders:pdv")

        request.session.pop(PDV_DRAFT_SESSION_KEY, None)
        table_or_tab = request.POST.get("table_or_tab", "").strip()
        cart_data = request.POST.get("cart_data", "[]")

        try:
            cart_items = json.loads(cart_data)
        except json.JSONDecodeError:
            messages.warning(request, INVALID_CART_MESSAGE)
            return redirect("orders:pdv")

        if not isinstance(cart_items, list):
            messages.warning(request, INVALID_CART_MESSAGE)
            return redirect("orders:pdv")

        if not cart_items:
            messages.warning(request, "Adicione pelo menos um item ao pedido.")
            return redirect("orders:pdv")

        requested_quantities = defaultdict(lambda: Decimal("0.00"))
        product_order = []

        for item in cart_items:
            if not isinstance(item, dict):
                messages.warning(request, INVALID_CART_MESSAGE)
                return redirect("orders:pdv")

            product_id = parse_positive_integer(item.get("id"))
            quantity = parse_positive_integer(item.get("quantity"))

            if product_id is None or quantity is None:
                messages.warning(request, INVALID_CART_MESSAGE)
                return redirect("orders:pdv")

            if product_id not in requested_quantities:
                product_order.append(product_id)
            requested_quantities[product_id] += Decimal(quantity)

        products = Product.objects.filter(
            id__in=requested_quantities,
            company=company,
            active=True,
            product_type__in=SALEABLE_PRODUCT_TYPES,
        )
        products_by_id = {product.pk: product for product in products}

        if set(products_by_id) != set(requested_quantities):
            messages.warning(request, INVALID_CART_MESSAGE)
            return redirect("orders:pdv")

        validated_items = [
            {
                "product": products_by_id[product_id],
                "quantity": requested_quantities[product_id],
            }
            for product_id in product_order
        ]

        try:
            consumption_plan = build_sale_consumption_plan(
                items=validated_items,
                company=company,
            )
            shortages = get_stock_shortages(
                company=company,
                product_quantities=consumption_plan.product_quantities,
            )
        except RecipeServiceError as error:
            messages.warning(
                request,
                f"Não foi possível enviar a pré-venda. {error}",
            )
            return redirect("orders:pdv")
        except (PhysicalSaleQuantityError, StockServiceError):
            messages.warning(request, INVALID_CART_MESSAGE)
            return redirect("orders:pdv")

        if shortages:
            request.session[PDV_DRAFT_SESSION_KEY] = {
                "company_id": company.pk,
                "table_or_tab": table_or_tab,
                "cart": [
                    {
                        "id": str(item["product"].pk),
                        "name": item["product"].name,
                        "price": str(item["product"].sale_price),
                        "quantity": int(item["quantity"]),
                    }
                    for item in validated_items
                ],
            }
            messages.warning(
                request,
                build_stock_shortage_message(
                    shortages,
                    products_by_id,
                    requested_quantities,
                    consumption_plan,
                ),
            )
            return redirect("orders:pdv")

        with transaction.atomic():
            order = Order.objects.create(
                company=company,
                table_or_tab=table_or_tab,
                status="pre_sale",
                created_by=request.user,
            )

            for item in validated_items:
                OrderItem.objects.create(
                    order=order,
                    company=company,
                    product=item["product"],
                    quantity=item["quantity"],
                )

        messages.success(request, f"Pedido #{order.id} enviado como pré-venda.")
        return redirect("orders:order_detail", order_id=order.id)

    products = list(
        Product.objects
        .filter(
            company=company,
            active=True,
            product_type__in=SALEABLE_PRODUCT_TYPES,
        )
        .select_related("category", "unit")
        .order_by("category__name", "name")
    )
    availability_batch = get_products_availability(products, company=company)

    categories = defaultdict(list)

    for product in products:
        product.pdv_availability = (
            availability_batch.availability_by_product.get(product.pk)
        )
        product.pdv_availability_error = (
            availability_batch.errors_by_product.get(product.pk)
        )
        product.pdv_is_available = bool(
            product.pdv_availability
            and product.pdv_availability.available_quantity > 0
        )
        product.pdv_available_quantity = (
            format_stock_quantity(product.pdv_availability.available_quantity)
            if product.pdv_availability is not None
            else "0"
        )
        if product.pdv_availability_error is not None:
            product.pdv_unavailable_reason = friendly_recipe_error(
                product.pdv_availability_error
            )
        elif not product.pdv_is_available:
            limiter = (
                product.pdv_availability.limiting_component
                if product.pdv_availability is not None
                else None
            )
            if limiter is not None:
                product.pdv_unavailable_reason = (
                    f"Sem {limiter.ingredient.name} suficiente."
                )
            elif (
                product.inventory_role == "prepared"
                and product.preparation_mode == "pre_portioned"
            ):
                product.pdv_unavailable_reason = (
                    "Nenhuma unidade pronta para venda."
                )
            else:
                product.pdv_unavailable_reason = "Sem estoque disponível."
        else:
            product.pdv_unavailable_reason = ""

        category_name = (
            product.category.name
            if product.category_id
            else "Sem categoria"
        )
        categories[category_name].append(product)

    draft = request.session.pop(PDV_DRAFT_SESSION_KEY, {})
    if (
        not isinstance(draft, dict)
        or draft.get("company_id") != company.pk
    ):
        draft = {}

    initial_cart = draft.get("cart", [])
    if not isinstance(initial_cart, list):
        initial_cart = []

    initial_table_or_tab = draft.get("table_or_tab", "")
    if not isinstance(initial_table_or_tab, str):
        initial_table_or_tab = ""

    return render(
        request,
        "orders/pdv.html",
        {
            "company": company,
            "categories": dict(categories),
            "initial_cart": initial_cart,
            "initial_table_or_tab": initial_table_or_tab,
        },
    )


@login_required
@company_required
def orders_panel(request):
    company = request.current_company

    if not can_view_orders_panel(request.user):
        messages.warning(request, "Você não tem permissão para ver o painel de pedidos.")
        return redirect("orders:pdv")

    search_query = request.GET.get("q", "").strip()

    orders = (
        Order.objects
        .filter(company=company, status__in=["pre_sale", "sold", "delivered"])
        .select_related("company", "created_by", "approved_by", "sale")
        .prefetch_related(
            Prefetch(
                "items",
                queryset=order_items_for_company(company),
            )
        )
        .order_by("-created_at")
    )

    if search_query:
        search_filter = (
            Q(created_by__username__icontains=search_query)
            | Q(created_by__first_name__icontains=search_query)
            | Q(created_by__last_name__icontains=search_query)
            | Q(
                items__company=company,
                items__product__company=company,
                items__product__name__icontains=search_query,
            )
            | Q(table_or_tab__icontains=search_query)
        )

        numeric_query = "".join(character for character in search_query if character.isdigit())

        if numeric_query:
            search_filter |= Q(id=int(numeric_query))

        orders = orders.filter(search_filter).distinct()

    pre_sale_orders = orders.filter(status="pre_sale")
    preparing_orders = orders.filter(status="sold")
    delivered_orders = orders.filter(status="delivered")

    return render(
        request,
        "orders/orders_panel.html",
        {
            "search_query": search_query,
            "total_active_orders": orders.count(),
            "pre_sale_orders": pre_sale_orders,
            "pre_sale_count": pre_sale_orders.count(),
            "preparing_orders": preparing_orders,
            "preparing_count": preparing_orders.count(),
            "delivered_orders": delivered_orders,
            "delivered_count": delivered_orders.count(),
            "can_approve_order": can_approve_order(request.user),
            "can_mark_delivered": can_mark_delivered(request.user),
            "can_cancel_pre_sale": can_cancel_pre_sale(request.user),
            "can_cancel_paid_order": can_cancel_paid_order(request.user),
            "can_discard_paid_order": can_discard_paid_order(request.user),
        },
    )


@login_required
@company_required
def order_detail(request, order_id):
    company = request.current_company
    order = get_object_or_404(
        Order.objects
        .select_related("company", "created_by", "approved_by", "sale")
        .prefetch_related(
            Prefetch(
                "items",
                queryset=order_items_for_company(company),
            )
        ),
        id=order_id,
        company=company,
    )

    can_view_this_order = (
        can_view_orders_panel(request.user)
        or order.created_by_id == request.user.id
    )

    if not can_view_this_order:
        messages.warning(request, "Você não tem permissão para ver este pedido.")
        return redirect("orders:pdv")

    return render(
        request,
        "orders/order_detail.html",
        {
            "order": order,
            "can_access_pdv": can_access_pdv(request.user),
            "can_view_orders_panel": can_view_orders_panel(request.user),
            "can_approve_order": can_approve_order(request.user),
            "can_mark_delivered": can_mark_delivered(request.user),
            "can_cancel_pre_sale": can_cancel_pre_sale(request.user),
            "can_cancel_paid_order": can_cancel_paid_order(request.user),
            "can_discard_paid_order": can_discard_paid_order(request.user),
        },
    )


@login_required
@company_required
@require_POST
def approve_order(request, order_id, payment_method):
    company = request.current_company

    if not can_approve_order(request.user):
        messages.warning(request, "Você não tem permissão para aprovar vendas.")
        return redirect("orders:order_detail", order_id=order_id)

    order = get_object_or_404(Order, id=order_id, company=company)

    valid_payment_methods = {value for value, _label in Sale.PAYMENT_METHODS}

    if payment_method not in valid_payment_methods:
        messages.warning(request, "Forma de pagamento inválida.")
        return redirect("orders:order_detail", order_id=order.id)

    try:
        result = approve_order_service(
            order_id=order.id,
            company=company,
            payment_method=payment_method,
            user=request.user,
        )
    except InsufficientStock as error:
        messages.warning(
            request,
            build_approval_shortage_message(
                order=order,
                company=company,
                shortage=error,
            ),
        )
    except (OrderServiceError, RecipeServiceError, StockServiceError) as error:
        messages.warning(request, str(error))
    else:
        if result.created:
            messages.success(request, f"Pedido #{order.id} aprovado com sucesso.")
        else:
            messages.info(request, f"Pedido #{order.id} já estava aprovado.")

    return redirect("orders:order_detail", order_id=order.id)


@login_required
@company_required
@require_POST
def mark_order_delivered(request, order_id):
    company = request.current_company

    if not can_mark_delivered(request.user):
        messages.warning(request, "Você não tem permissão para marcar pedidos como entregues.")
        return redirect("orders:order_detail", order_id=order_id)

    order = get_object_or_404(Order, id=order_id, company=company)
    result = mark_order_delivered_service(order_id=order.id, company=company)

    if result.changed:
        messages.success(request, f"Pedido #{order.id} marcado como entregue.")
    else:
        messages.info(request, f"Pedido #{order.id} não estava aguardando entrega.")

    return redirect("orders:order_detail", order_id=order.id)


@login_required
@company_required
@require_POST
def cancel_order(request, order_id):
    company = request.current_company

    if not can_cancel_pre_sale(request.user):
        messages.warning(request, "Você não tem permissão para cancelar pré-vendas.")
        return redirect("orders:order_detail", order_id=order_id)

    order = get_object_or_404(Order, id=order_id, company=company)
    result = cancel_pre_sale_order_service(order_id=order.id, company=company)

    if result.changed:
        messages.warning(request, f"Pedido #{order.id} cancelado.")
    else:
        messages.info(request, f"Pedido #{order.id} não estava em pré-venda.")

    return redirect("orders:order_detail", order_id=order.id)


@login_required
@company_required
@require_POST
def cancel_paid_order_with_stock_return(request, order_id):
    company = request.current_company

    if not can_cancel_paid_order(request.user):
        messages.warning(
            request,
            "Você não tem permissão para cancelar vendas e devolver estoque.",
        )
        return redirect("orders:order_detail", order_id=order_id)

    order = get_object_or_404(Order, id=order_id, company=company)
    try:
        result = cancel_paid_order_with_stock_return_service(
            order_id=order.id,
            company=company,
            user=request.user,
        )
    except UntraceableSaleStock:
        messages.warning(
            request,
            "Esta venda é legada e não possui rastreabilidade suficiente para "
            "um retorno automático seguro.",
        )
    except (OrderServiceError, StockServiceError) as error:
        messages.warning(request, str(error))
    else:
        if result.restored:
            messages.warning(
                request,
                f"Pedido #{order.id} cancelado e itens retornados ao estoque.",
            )
        else:
            messages.info(
                request,
                f"Pedido #{order.id} já estava cancelado; nenhum novo retorno foi feito.",
            )

    return redirect("orders:order_detail", order_id=order.id)


@login_required
@company_required
@require_POST
def discard_paid_order(request, order_id):
    company = request.current_company

    if not can_discard_paid_order(request.user):
        messages.warning(
            request,
            "Você não tem permissão para descartar vendas.",
        )
        return redirect("orders:order_detail", order_id=order_id)

    order = get_object_or_404(Order, id=order_id, company=company)
    result = discard_paid_order_service(
        order_id=order.id,
        company=company,
        user=request.user,
    )

    if result.changed:
        messages.warning(
            request,
            f"Pedido #{order.id} descartado. Os itens não voltaram ao estoque.",
        )
    else:
        messages.info(request, f"Pedido #{order.id} não estava apto ao descarte.")

    return redirect("orders:order_detail", order_id=order.id)
