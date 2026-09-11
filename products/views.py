from io import BytesIO
from decimal import Decimal, InvalidOperation
from xml.sax.saxutils import escape

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import (
    Case,
    DecimalField,
    ExpressionWrapper,
    F,
    Q,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from accounts.permissions import (
    can_adjust_stock,
    can_create_stock_entry,
    can_view_stock,
    company_required,
)

from .category_names import clean_category_name
from .category_services import resolve_category
from .forms import (
    ProductComponentFormSet,
    ProductCreateForm,
    ProductionConsumptionFormSet,
    ProductionForm,
    StockEntryForm,
)
from .models import Product, ProductComponent, Production, Unit
from .production_services import (
    ProductionServiceError,
    create_production,
    reverse_production,
)
from .recipe_services import (
    RecipeServiceError,
    expand_product_components,
    get_product_availability,
    get_production_potential,
)
from .sale_quantities import PhysicalSaleQuantityError, get_sale_availability
from .services import (
    StockEntryValidationError,
    StockServiceError,
    apply_stock_count,
    create_stock_entry,
)


def parse_decimal(value):
    if value is None:
        return None

    value = str(value).strip().replace(",", ".")

    if value == "":
        return None

    try:
        parsed = Decimal(value)
    except InvalidOperation:
        return None

    return parsed if parsed.is_finite() else None


def format_quantity(value):
    formatted = f"{value or Decimal('0'):.6f}".rstrip("0").rstrip(".")
    return formatted.replace(".", ",")


def _get_stock_products_queryset(company):
    current_stock_field = DecimalField(max_digits=20, decimal_places=6)
    average_cost_field = DecimalField(max_digits=30, decimal_places=10)
    stock_cost_expression = ExpressionWrapper(
        F("stock_entries__remaining_quantity")
        * F("stock_entries__total_cost")
        / F("stock_entries__quantity_added"),
        output_field=average_cost_field,
    )

    return (
        Product.objects
        .filter(company=company, active=True)
        .select_related("category", "company", "unit")
        .annotate(
            annotated_current_stock=Coalesce(
                Sum(
                    "stock_entries__remaining_quantity",
                    filter=Q(stock_entries__company=company),
                ),
                Value(Decimal("0.00")),
                output_field=current_stock_field,
            ),
            report_current_stock=Coalesce(
                Sum(
                    "stock_entries__remaining_quantity",
                    filter=Q(stock_entries__company=company),
                ),
                Value(Decimal("0.00")),
                output_field=current_stock_field,
            ),
            annotated_average_cost_quantity=Coalesce(
                Sum(
                    Case(
                        When(
                            stock_entries__company=company,
                            stock_entries__remaining_quantity__gt=0,
                            then=F("stock_entries__remaining_quantity"),
                        ),
                        default=Value(Decimal("0.00")),
                        output_field=current_stock_field,
                    )
                ),
                Value(Decimal("0.00")),
                output_field=current_stock_field,
            ),
            annotated_average_cost_total=Coalesce(
                Sum(
                    Case(
                        When(
                            stock_entries__company=company,
                            stock_entries__remaining_quantity__gt=0,
                            stock_entries__quantity_added__gt=0,
                            then=stock_cost_expression,
                        ),
                        default=Value(Decimal("0.00")),
                        output_field=average_cost_field,
                    )
                ),
                Value(Decimal("0.00")),
                output_field=average_cost_field,
            ),
        )
        .order_by("category__name", "name")
    )


def stock_report_products_for_company(company):
    """Return the tenant-scoped queryset shared by stock reports."""
    return _get_stock_products_queryset(company)


@login_required
@company_required
def stock_dashboard(request):
    if not can_view_stock(request.user):
        messages.warning(request, "Você não tem permissão para ver o estoque.")
        return redirect("orders:pdv")

    company = request.current_company
    products = stock_report_products_for_company(company)
    for product in products:
        product.display_stock_status = product.stock_status
        product.display_stock_status_label = product.stock_status_label
        product.sale_availability = None
        product.recipe_availability = None
        product.recipe_error = None
        product.production_potential = None
        product.production_error = None
        if (
            product.inventory_role == "prepared"
            and product.preparation_mode == "on_demand"
        ):
            try:
                product.recipe_availability = get_product_availability(product)
                if product.recipe_availability.available_quantity > 0:
                    product.display_stock_status = "ok"
                    product.display_stock_status_label = "Disponível"
                else:
                    product.display_stock_status = "empty"
                    product.display_stock_status_label = (
                        "Esgotado por ingrediente"
                    )
            except RecipeServiceError as error:
                product.recipe_error = str(error)
                product.display_stock_status = "empty"
                product.display_stock_status_label = "Receita inválida"
            continue
        if (
            product.inventory_role == "prepared"
            and product.preparation_mode == "pre_portioned"
        ):
            try:
                product.sale_availability = get_sale_availability(
                    product,
                    product.current_stock,
                )
            except PhysicalSaleQuantityError:
                pass
            try:
                product.production_potential = get_production_potential(product)
            except RecipeServiceError as error:
                product.production_error = str(error)
            continue
        if product.sale_form not in {"dose", "portion"}:
            continue
        try:
            product.sale_availability = get_sale_availability(
                product,
                product.current_stock,
            )
        except PhysicalSaleQuantityError:
            # Legacy invalid configurations remain visible as physical stock.
            pass

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
@company_required
@require_GET
def shopping_list(request):
    if not can_view_stock(request.user):
        messages.warning(request, "Você não tem permissão para ver o estoque.")
        return redirect("orders:pdv")

    company = request.current_company

    status_filters = [
        {"key": "buy", "label": "Comprar"},
        {"key": "empty", "label": "Esgotado"},
        {"key": "critical", "label": Product.STOCK_STATUS_LABELS["critical"]},
        {"key": "low", "label": Product.STOCK_STATUS_LABELS["low"]},
        {"key": "ok", "label": Product.STOCK_STATUS_LABELS["ok"]},
    ]
    valid_statuses = {status_filter["key"] for status_filter in status_filters}
    selected_status = request.GET.get("status", "buy")

    if selected_status not in valid_statuses:
        selected_status = "buy"

    buying_statuses = {"empty", "critical", "low"}
    counts = {status_filter["key"]: 0 for status_filter in status_filters}
    rows = []

    for product in _get_stock_products_queryset(company):
        current_stock = product.current_stock
        recommended_stock = product.minimum_quantity or Decimal("0.00")
        status = product.stock_status
        suggested_quantity = recommended_stock - current_stock

        if suggested_quantity < 0:
            suggested_quantity = Decimal("0.00")

        row = {
            "product": product,
            "category": (
                product.category.name
                if product.category_id
                else "Sem categoria"
            ),
            "current_stock": current_stock,
            "recommended_stock": recommended_stock,
            "recommended_defined": recommended_stock > 0,
            "status": status,
            "status_label": product.stock_status_label,
            "suggested_quantity": suggested_quantity,
            "unit": product.stock_base_unit_label,
        }

        counts[status] += 1

        if status in buying_statuses:
            counts["buy"] += 1

        if selected_status == "buy" and status in buying_statuses:
            rows.append(row)
        elif selected_status == status:
            rows.append(row)

    filter_options = []

    for status_filter in status_filters:
        filter_options.append({
            "key": status_filter["key"],
            "label": status_filter["label"],
            "count": counts[status_filter["key"]],
            "active": status_filter["key"] == selected_status,
        })

    selected_filter_label = next(
        status_filter["label"]
        for status_filter in status_filters
        if status_filter["key"] == selected_status
    )

    return render(
        request,
        "products/shopping_list.html",
        {
            "company": company,
            "emitted_at": timezone.localtime(),
            "filter_options": filter_options,
            "rows": rows,
            "selected_filter_label": selected_filter_label,
            "selected_status": selected_status,
        },
    )


@login_required
@company_required
@require_GET
def stock_report_pdf(request):
    if not can_view_stock(request.user):
        messages.warning(request, "Você não tem permissão para ver o estoque.")
        return redirect("orders:pdv")

    company = request.current_company
    products = _get_stock_products_queryset(company)

    emitted_at = timezone.localtime()
    filename = f"estoque_geral_{emitted_at:%Y%m%d_%H%M}.pdf"
    buffer = BytesIO()

    document = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=12 * mm,
        leftMargin=12 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title="Relatório Geral de Estoque",
        author=company.name,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "StockReportTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=17,
        leading=20,
        textColor=colors.HexColor("#111827"),
        spaceAfter=8,
    )
    meta_style = ParagraphStyle(
        "StockReportMeta",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#4B5563"),
    )
    cell_style = ParagraphStyle(
        "StockReportCell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#111827"),
    )

    story = [
        Paragraph("Relatório Geral de Estoque", title_style),
        Paragraph(f"<b>Empresa:</b> {escape(company.name)}", meta_style),
        Paragraph(
            f"<b>Emitido em:</b> {emitted_at:%d/%m/%Y às %H:%M}",
            meta_style,
        ),
        Spacer(1, 6 * mm),
    ]

    table_data = [[
        "Produto",
        "Categoria",
        "Unidade",
        "Estoque atual",
        "Estoque recomendado",
        "Status",
        "Preço de venda",
    ]]

    for product in products:
        current_stock = product.current_stock
        status = Product.get_stock_status_label(
            current_stock,
            product.minimum_quantity,
        )

        recommended_stock = (
            format_quantity(product.minimum_quantity)
            if product.minimum_quantity > 0
            else "-"
        )

        table_data.append([
            Paragraph(escape(product.name), cell_style),
            Paragraph(
                escape(
                    product.category.name
                    if product.category_id
                    else "Sem categoria"
                ),
                cell_style,
            ),
            escape(product.stock_base_unit_label),
            format_quantity(current_stock),
            recommended_stock,
            status,
            f"R$ {product.sale_price:.2f}".replace(".", ","),
        ])

    table = Table(
        table_data,
        colWidths=[55 * mm, 36 * mm, 22 * mm, 30 * mm, 38 * mm, 28 * mm, 34 * mm],
        repeatRows=1,
        hAlign="LEFT",
    )
    table_style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F2937")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("ALIGN", (2, 1), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D1D5DB")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F9FAFB")]),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]
    table.setStyle(TableStyle(table_style))
    story.append(table)

    def add_page_number(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#6B7280"))
        canvas.drawRightString(
            landscape(A4)[0] - 12 * mm,
            8 * mm,
            f"Página {doc.page}",
        )
        canvas.restoreState()

    document.build(
        story,
        onFirstPage=add_page_number,
        onLaterPages=add_page_number,
    )

    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


PRODUCT_ADVANCED_FIELDS = {
    "category",
    "product_type",
    "unit",
    "inventory_role",
    "stock_dimension",
    "unit_description",
    "dose_ml",
    "portion_g",
    "preparation_mode",
    "minimum_quantity",
    "active",
}


def _add_validation_error(target_form, error):
    if hasattr(error, "message_dict"):
        for field_name, field_messages in error.message_dict.items():
            target_field = field_name if field_name in target_form.fields else None
            for field_message in field_messages:
                target_form.add_error(target_field, field_message)
        return

    for field_message in error.messages:
        target_form.add_error(None, field_message)


def _render_product_create(
    request,
    *,
    company,
    form,
    component_formset,
    submission_failed=False,
):
    advanced_errors = any(
        field_name in form.errors for field_name in PRODUCT_ADVANCED_FIELDS
    )
    advanced_errors = advanced_errors or any(
        bool(component_errors) for component_errors in component_formset.errors
    )
    advanced_errors = advanced_errors or bool(component_formset.non_form_errors())

    return render(
        request,
        "products/product_form.html",
        {
            "form": form,
            "component_formset": component_formset,
            "submission_failed": submission_failed,
            "advanced_errors": advanced_errors,
            "units": Unit.objects.filter(company=company).order_by("name"),
            "product_types": Product.PRODUCT_TYPES,
            "inventory_roles": Product.INVENTORY_ROLES,
            "sale_forms": Product.SALE_FORMS,
            "stock_dimensions": Product.STOCK_DIMENSIONS,
            "preparation_modes": Product.PREPARATION_MODES,
        },
    )


@login_required
@company_required
def product_create(request):
    if not can_create_stock_entry(request.user):
        messages.warning(request, "Você não tem permissão para cadastrar produtos.")
        return redirect("products:stock_dashboard")

    company = request.current_company
    form = ProductCreateForm(
        request.POST if request.method == "POST" else None,
        company=company,
    )
    components_submitted = (
        request.method == "POST" and "components-TOTAL_FORMS" in request.POST
    )
    component_formset = ProductComponentFormSet(
        request.POST if components_submitted else None,
        prefix="components",
        form_kwargs={"company": company},
    )

    if request.method == "POST":
        if "category_id" in request.POST:
            messages.warning(request, "Os dados informados para o produto são inválidos.")
            return redirect("products:product_create")

        posted_unit_id = request.POST.get("unit")
        if posted_unit_id:
            get_object_or_404(Unit, id=posted_unit_id, company=company)

        forms_are_valid = form.is_valid()
        components_are_valid = (
            component_formset.is_valid() if components_submitted else True
        )
        if not forms_are_valid or not components_are_valid:
            return _render_product_create(
                request,
                company=company,
                form=form,
                component_formset=component_formset,
                submission_failed=True,
            )

        data = form.cleaned_data
        if (
            data["inventory_role"] == "prepared"
            and data.get("preparation_mode") == "on_demand"
        ):
            valid_component_count = 0
            if components_submitted:
                valid_component_count = sum(
                    1
                    for component_form in component_formset
                    if component_form.cleaned_data
                    and not component_form.cleaned_data.get("DELETE")
                )
            if valid_component_count == 0:
                form.add_error(
                    "preparation_mode",
                    "Produto preparado sob demanda precisa de ao menos um componente.",
                )
                return _render_product_create(
                    request,
                    company=company,
                    form=form,
                    component_formset=component_formset,
                    submission_failed=True,
                )

        name = data["name"].strip()
        category_text = clean_category_name(data.get("category"))

        validation_target = form
        try:
            with transaction.atomic():
                category = resolve_category(
                    company=company,
                    raw_name=category_text,
                )
                unit = data.get("unit")
                if unit is None:
                    legacy_units = {
                        "count": ("Unidade", "un"),
                        "weight": ("Grama", "g"),
                        "volume": ("Mililitro", "mL"),
                    }
                    unit_name, unit_symbol = legacy_units[data["stock_dimension"]]
                    unit, _created = Unit.objects.get_or_create(
                        company=company,
                        symbol=unit_symbol,
                        defaults={"name": unit_name},
                    )

                product = Product.objects.create(
                    company=company,
                    name=name,
                    category=category,
                    category_legacy=category_text or None,
                    product_type=data["product_type"],
                    inventory_role=data["inventory_role"],
                    sale_form=data["sale_form"],
                    stock_dimension=data["stock_dimension"],
                    unit_description=data.get("unit_description", "").strip(),
                    dose_ml=data.get("dose_ml"),
                    portion_g=data.get("portion_g"),
                    preparation_mode=data.get("preparation_mode"),
                    unit=unit,
                    sale_price=data["sale_price"],
                    minimum_quantity=data["minimum_quantity"],
                    active=data["active"],
                )

                if components_submitted:
                    for component_form in component_formset:
                        component_data = component_form.cleaned_data
                        if not component_data or component_data.get("DELETE"):
                            continue

                        validation_target = component_form
                        ProductComponent.objects.create(
                            company=company,
                            product=product,
                            ingredient=component_data["ingredient"],
                            quantity=component_data["quantity"],
                            unit=component_data["unit"],
                        )
        except ValidationError as error:
            _add_validation_error(validation_target, error)
            return _render_product_create(
                request,
                company=company,
                form=form,
                component_formset=component_formset,
                submission_failed=True,
            )

        messages.success(request, f"Produto cadastrado: {name}.")
        return redirect("products:stock_dashboard")

    return _render_product_create(
        request,
        company=company,
        form=form,
        component_formset=component_formset,
    )


@login_required
@company_required
def stock_entry_create(request):
    if not can_create_stock_entry(request.user):
        messages.warning(
            request,
            "Voc\u00ea n\u00e3o tem permiss\u00e3o para inserir estoque.",
        )
        return redirect("products:stock_dashboard")

    company = request.current_company
    products = (
        Product.objects.filter(company=company, active=True)
        .select_related("category", "unit")
        .order_by("category__name", "name")
    )

    submitted_product_id = (
        request.POST.get("product") if request.method == "POST" else None
    )
    try:
        submitted_product_id = int(submitted_product_id)
    except (TypeError, ValueError):
        submitted_product_id = None
    if submitted_product_id is not None:
        get_object_or_404(
            Product,
            pk=submitted_product_id,
            company=company,
            active=True,
        )

    form = StockEntryForm(
        request.POST if request.method == "POST" else None,
        company=company,
    )
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            entry = create_stock_entry(
                company=company,
                product=data["product"],
                input_quantity=data["input_quantity"],
                input_unit=data["input_unit"],
                price_mode=data["price_mode"],
                price=data["price"],
                entry_date=data["entry_date"],
                expiration_date=data.get("expiration_date"),
                notes=data.get("notes"),
                created_by=request.user,
            )
        except StockEntryValidationError as error:
            target_field = error.field if error.field in form.fields else None
            form.add_error(target_field, str(error))
        else:
            messages.success(
                request,
                (
                    f"Entrada criada: {entry.product.name} recebeu "
                    f"{format_quantity(entry.input_quantity)} {entry.input_unit}."
                ),
            )
            return redirect("products:stock_dashboard")

    selected_product = None
    if form.is_bound and submitted_product_id is not None:
        selected_product = products.filter(pk=submitted_product_id).first()

    return render(
        request,
        "products/stock_entry_form.html",
        {
            "form": form,
            "products": products,
            "selected_product": selected_product,
        },
    )


@login_required
@company_required
def stock_count_adjust(request):
    if not can_adjust_stock(request.user):
        messages.warning(request, "Você não tem permissão para fazer conferência de estoque.")
        return redirect("products:stock_dashboard")

    company = request.current_company

    products = (
        Product.objects
        .filter(company=company, active=True)
        .select_related("category", "unit")
        .order_by("category__name", "name")
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

        try:
            result = apply_stock_count(
                company=company,
                product=product,
                real_quantity=real_quantity,
                notes=notes,
                created_by=request.user,
            )
        except StockServiceError as error:
            messages.warning(request, str(error))
            return redirect("products:stock_count_adjust")

        if result.difference == 0:
            messages.success(
                request,
                f"Conferência registrada para {product.name}. Sem diferença no estoque.",
            )
            return redirect("products:stock_dashboard")

        if result.difference > 0:
            messages.success(
                request,
                f"{product.name}: ajuste positivo de {result.difference} "
                f"{product.stock_base_unit_label} aplicado.",
            )

            return redirect("products:stock_dashboard")

        quantity_to_remove = abs(result.difference)

        messages.warning(
            request,
            f"{product.name}: ajuste negativo de {quantity_to_remove} "
            f"{product.stock_base_unit_label} aplicado.",
        )

        return redirect("products:stock_dashboard")

    return render(
        request,
        "products/stock_count_form.html",
        {
            "products": products,
        },
    )


def _pre_portioned_product(company, product_id):
    return get_object_or_404(
        Product.objects.select_related("company", "unit", "category"),
        pk=product_id,
        company=company,
        active=True,
        inventory_role="prepared",
        preparation_mode="pre_portioned",
    )


def _production_rows(expanded_components, formset):
    availability_by_ingredient = {}
    if expanded_components:
        potential = get_production_potential(
            expanded_components[0].source_component.product
        )
        availability_by_ingredient = {
            item.ingredient.pk: item
            for item in potential.component_availability
        }
    rows = []
    for component, component_form in zip(expanded_components, formset.forms):
        availability = availability_by_ingredient.get(component.ingredient.pk)
        rows.append(
            {
                "component": component,
                "form": component_form,
                "physical_stock": (
                    availability.physical_stock if availability else Decimal("0")
                ),
                "sufficient": (
                    availability is not None
                    and availability.physical_stock >= component.total_quantity
                ),
            }
        )
    return rows


@login_required
@company_required
def production_create(request, product_id):
    if not can_adjust_stock(request.user):
        messages.warning(request, "Você não tem permissão para registrar produção.")
        return redirect("products:stock_dashboard")

    company = request.current_company
    product = _pre_portioned_product(company, product_id)
    recipe_error = None
    try:
        potential = get_production_potential(product)
    except RecipeServiceError as error:
        potential = None
        recipe_error = str(error)

    if request.method == "POST":
        form = ProductionForm(request.POST)
        formset = ProductionConsumptionFormSet(
            request.POST,
            prefix="consumption",
        )
        if form.is_valid() and formset.is_valid():
            component_values = {
                component_form.cleaned_data["component_id"]: {
                    "actual_quantity": component_form.cleaned_data[
                        "actual_quantity"
                    ],
                    "loss_quantity": component_form.cleaned_data[
                        "loss_quantity"
                    ],
                }
                for component_form in formset.forms
            }
            try:
                result = create_production(
                    company=company,
                    product=product,
                    planned_quantity=form.cleaned_data["planned_quantity"],
                    produced_quantity=form.cleaned_data["produced_quantity"],
                    production_date=form.cleaned_data["production_date"],
                    expiration_date=form.cleaned_data.get("expiration_date"),
                    component_values=component_values,
                    notes=form.cleaned_data.get("notes"),
                    created_by=request.user,
                )
            except (RecipeServiceError, StockServiceError) as error:
                form.add_error(None, str(error))
            else:
                messages.success(
                    request,
                    f"Produção #{result.production.pk} registrada com sucesso.",
                )
                return redirect(
                    "products:production_detail",
                    production_id=result.production.pk,
                )
        planned = form.cleaned_data.get("planned_quantity") if form.is_bound else None
        if planned is None:
            planned = parse_decimal(request.POST.get("planned_quantity"))
        expanded_components = ()
        if planned is not None and planned > 0 and recipe_error is None:
            try:
                expanded_components = expand_product_components(product, planned)
            except RecipeServiceError as error:
                recipe_error = str(error)
        rows = _production_rows(expanded_components, formset)
    else:
        default_quantity = (
            potential.available_quantity
            if potential is not None and potential.available_quantity > 0
            else Decimal("1")
        )
        form = ProductionForm(
            initial={
                "planned_quantity": default_quantity,
                "produced_quantity": default_quantity,
                "production_date": timezone.localdate(),
            }
        )
        expanded_components = ()
        if recipe_error is None:
            try:
                expanded_components = expand_product_components(
                    product,
                    default_quantity,
                )
            except RecipeServiceError as error:
                recipe_error = str(error)
        formset = ProductionConsumptionFormSet(
            initial=[
                {
                    "component_id": component.source_component.pk,
                    "actual_quantity": component.total_quantity,
                    "loss_quantity": Decimal("0"),
                }
                for component in expanded_components
            ],
            prefix="consumption",
        )
        rows = _production_rows(expanded_components, formset)

    return render(
        request,
        "products/production_form.html",
        {
            "product": product,
            "potential": potential,
            "recipe_error": recipe_error,
            "form": form,
            "formset": formset,
            "rows": rows,
        },
    )


@login_required
@company_required
def production_list(request):
    if not can_view_stock(request.user):
        messages.warning(request, "Você não tem permissão para ver produções.")
        return redirect("orders:pdv")
    productions = (
        Production.objects.filter(company=request.current_company)
        .select_related("product", "created_by", "reversed_by")
        .order_by("-production_date", "-id")
    )
    return render(
        request,
        "products/production_list.html",
        {"productions": productions},
    )


@login_required
@company_required
def production_detail(request, production_id):
    if not can_view_stock(request.user):
        messages.warning(request, "Você não tem permissão para ver produções.")
        return redirect("orders:pdv")
    production = get_object_or_404(
        Production.objects.select_related(
            "product",
            "created_by",
            "reversed_by",
        ),
        pk=production_id,
        company=request.current_company,
    )
    consumptions = list(
        production.consumptions.select_related("ingredient").order_by(
            "ingredient__name",
            "id",
        )
    )
    for consumption in consumptions:
        consumption.allocations = list(
            consumption.stock_movements.filter(
                movement_type="production_consumption"
            )
            .select_related("stock_entry")
            .order_by("stock_entry__created_at", "stock_entry_id")
        )
    output_entry = getattr(production, "output_stock_entry", None)
    return render(
        request,
        "products/production_detail.html",
        {
            "production": production,
            "consumptions": consumptions,
            "output_entry": output_entry,
            "can_reverse": (
                can_adjust_stock(request.user)
                and production.status == Production.STATUS_COMPLETED
            ),
        },
    )


@login_required
@company_required
@require_POST
def production_reverse(request, production_id):
    if not can_adjust_stock(request.user):
        messages.warning(request, "Você não tem permissão para reverter produção.")
        return redirect(
            "products:production_detail",
            production_id=production_id,
        )
    try:
        result = reverse_production(
            company=request.current_company,
            production_id=production_id,
            user=request.user,
        )
    except ProductionServiceError as error:
        messages.warning(request, str(error))
    else:
        if result.reversed:
            messages.success(request, f"Produção #{production_id} revertida.")
        else:
            messages.info(request, f"Produção #{production_id} já estava revertida.")
    return redirect(
        "products:production_detail",
        production_id=production_id,
    )
