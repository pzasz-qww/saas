from io import BytesIO
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode, urlsplit
from xml.sax.saxutils import escape

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
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
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import Resolver404, resolve, reverse
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
from .models import Product, ProductComponent, Production, StockEntry, Unit
from .presentation import (
    format_decimal_input,
    format_money,
    format_quantity,
    friendly_recipe_error,
)
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
    calculate_fifo_cost,
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


def _query_selected_product(products, raw_product_id):
    if raw_product_id in (None, ""):
        return None
    try:
        product_id = int(raw_product_id)
    except (TypeError, ValueError):
        raise Http404("Produto inválido.") from None
    return get_object_or_404(products, pk=product_id)


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
        .prefetch_related("components__ingredient")
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
                product.recipe_error = friendly_recipe_error(error)
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
                product.production_error = friendly_recipe_error(error)
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
            format_quantity(product.minimum_quantity, product.stock_base_unit)
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
            format_quantity(current_stock, product.stock_base_unit),
            recommended_stock,
            status,
            format_money(product.sale_price),
        ])

    table = Table(
        table_data,
        colWidths=[60 * mm, 40 * mm, 40 * mm, 45 * mm, 30 * mm, 36 * mm],
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
    "stock_dimension",
    "unit_description",
    "dose_ml",
    "portion_g",
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


def _product_form_initial(product):
    return {
        "name": product.name,
        "sale_price": product.sale_price,
        "sale_form": product.sale_form,
        "category": (
            product.category.name
            if product.category_id
            else product.category_legacy or ""
        ),
        "product_type": product.product_type,
        "unit": product.unit_id,
        "inventory_role": product.inventory_role,
        "stock_dimension": product.stock_dimension,
        "unit_description": product.unit_description,
        "dose_ml": (
            format_decimal_input(product.dose_ml)
            if product.dose_ml is not None
            else None
        ),
        "portion_g": (
            format_decimal_input(product.portion_g)
            if product.portion_g is not None
            else None
        ),
        "preparation_mode": product.preparation_mode or "",
        "minimum_quantity": format_decimal_input(product.minimum_quantity),
        "active": product.active,
    }


def _safe_recipe_return_url(*, company, raw_url):
    if not raw_url:
        return None

    parsed = urlsplit(str(raw_url))
    if (
        parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith("/")
    ):
        return None

    try:
        match = resolve(parsed.path)
    except Resolver404:
        return None
    if match.view_name != "products:product_edit":
        return None

    product_id = match.kwargs.get("product_id")
    if not Product.objects.filter(
        pk=product_id,
        company=company,
        inventory_role="prepared",
    ).exists():
        return None
    return reverse("products:product_edit", args=[product_id])


def _component_form_initial(components):
    return [
        {
            "component_id": component.pk,
            "ingredient": component.ingredient_id,
            "quantity": format_decimal_input(component.quantity),
            "unit": component.unit,
        }
        for component in components
    ]


def _resolve_product_unit(*, company, data):
    unit = data.get("unit")
    if unit is not None:
        return unit

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
    return unit


def _apply_product_data(*, product, data, category, unit):
    product.name = data["name"].strip()
    product.category = category
    product.category_legacy = clean_category_name(data.get("category")) or None
    product.product_type = data["product_type"]
    product.inventory_role = data["inventory_role"]
    product.sale_form = data["sale_form"]
    product.stock_dimension = data["stock_dimension"]
    product.unit_description = data.get("unit_description", "").strip()
    product.dose_ml = data.get("dose_ml")
    product.portion_g = data.get("portion_g")
    product.preparation_mode = data.get("preparation_mode")
    product.unit = unit
    product.sale_price = data["sale_price"]
    product.minimum_quantity = data["minimum_quantity"]
    product.active = data["active"]


def _product_availability_context(product):
    context = {
        "edit_availability": None,
        "edit_availability_error": None,
        "edit_ready_availability": None,
        "edit_production_potential": None,
        "edit_production_error": None,
    }
    if product is None or product.inventory_role != "prepared":
        return context

    if product.preparation_mode == "on_demand":
        try:
            context["edit_availability"] = get_product_availability(product)
        except RecipeServiceError as error:
            context["edit_availability_error"] = friendly_recipe_error(error)
        return context

    if product.preparation_mode == "pre_portioned":
        try:
            context["edit_ready_availability"] = get_sale_availability(
                product,
                product.current_stock,
            )
        except PhysicalSaleQuantityError as error:
            context["edit_availability_error"] = str(error)
        try:
            context["edit_production_potential"] = get_production_potential(product)
        except RecipeServiceError as error:
            context["edit_production_error"] = friendly_recipe_error(error)
    return context


def _render_product_form(
    request,
    *,
    company,
    form,
    component_formset,
    product=None,
    submission_failed=False,
    creating_input=False,
    recipe_return_to=None,
):
    advanced_errors = any(
        field_name in form.errors for field_name in PRODUCT_ADVANCED_FIELDS
    )
    advanced_errors = advanced_errors or "preparation_mode" in form.errors
    advanced_errors = advanced_errors or any(
        bool(component_errors) for component_errors in component_formset.errors
    )
    advanced_errors = advanced_errors or bool(component_formset.non_form_errors())

    context = {
        "form": form,
        "component_formset": component_formset,
        "product": product,
        "editing": product is not None,
        "submission_failed": submission_failed,
        "creating_input": creating_input,
        "recipe_return_to": recipe_return_to,
        "advanced_errors": advanced_errors,
        "units": Unit.objects.filter(company=company).order_by("name"),
        "product_types": Product.PRODUCT_TYPES,
        "inventory_roles": Product.INVENTORY_ROLES,
        "sale_forms": Product.SALE_FORMS,
        "stock_dimensions": Product.STOCK_DIMENSIONS,
        "preparation_modes": Product.PREPARATION_MODES,
        "new_input_url": (
            f"{reverse('products:product_create')}?"
            f"{urlencode({'tipo': 'insumo', 'return_to': reverse('products:product_edit', args=[product.pk])})}"
            if product is not None and product.inventory_role == "prepared"
            else None
        ),
    }
    context.update(_product_availability_context(product))
    return render(
        request,
        "products/product_form.html",
        context,
    )


@login_required
@company_required
def product_create(request):
    if not can_create_stock_entry(request.user):
        messages.warning(request, "Você não tem permissão para cadastrar produtos.")
        return redirect("products:stock_dashboard")

    company = request.current_company
    raw_return_to = (
        request.POST.get("return_to")
        if request.method == "POST"
        else request.GET.get("return_to")
    )
    recipe_return_to = _safe_recipe_return_url(
        company=company,
        raw_url=raw_return_to,
    )
    creating_input = (
        request.POST.get("creation_mode") == "input"
        if request.method == "POST"
        else request.GET.get("tipo") == "insumo"
    )
    form_data = request.POST if request.method == "POST" else None
    if form_data is not None and creating_input:
        form_data = form_data.copy()
        form_data["inventory_role"] = "input"
        form_data["product_type"] = "internal_use"
        form_data["preparation_mode"] = ""
    form = ProductCreateForm(
        form_data,
        company=company,
        initial=(
            {
                "inventory_role": "input",
                "product_type": "internal_use",
                "sale_form": "unit",
            }
            if creating_input and request.method == "GET"
            else None
        ),
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
            return _render_product_form(
                request,
                company=company,
                form=form,
                component_formset=component_formset,
                submission_failed=True,
                creating_input=creating_input,
                recipe_return_to=recipe_return_to,
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
                return _render_product_form(
                    request,
                    company=company,
                    form=form,
                    component_formset=component_formset,
                    submission_failed=True,
                    creating_input=creating_input,
                    recipe_return_to=recipe_return_to,
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
                unit = _resolve_product_unit(company=company, data=data)

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
            return _render_product_form(
                request,
                company=company,
                form=form,
                component_formset=component_formset,
                submission_failed=True,
                creating_input=creating_input,
                recipe_return_to=recipe_return_to,
            )

        messages.success(
            request,
            f"{'Insumo' if creating_input else 'Produto'} cadastrado: {name}.",
        )
        if recipe_return_to:
            return redirect(recipe_return_to)
        return redirect("products:stock_dashboard")

    return _render_product_form(
        request,
        company=company,
        form=form,
        component_formset=component_formset,
        creating_input=creating_input,
        recipe_return_to=recipe_return_to,
    )


@login_required
@company_required
def product_edit(request, product_id):
    if not can_create_stock_entry(request.user):
        messages.warning(request, "Você não tem permissão para editar produtos.")
        return redirect("products:stock_dashboard")

    company = request.current_company
    product = get_object_or_404(
        Product.objects.select_related("category", "unit"),
        pk=product_id,
        company=company,
    )
    components = list(
        ProductComponent.objects.filter(company=company, product=product)
        .select_related("ingredient")
        .order_by("id")
    )
    component_ids = [component.pk for component in components]
    form = ProductCreateForm(
        request.POST if request.method == "POST" else None,
        company=company,
        initial=_product_form_initial(product),
    )
    component_formset = ProductComponentFormSet(
        request.POST if request.method == "POST" else None,
        prefix="components",
        initial=_component_form_initial(components),
        form_kwargs={"company": company},
        existing_component_ids=component_ids,
    )

    if request.method == "POST":
        if "category_id" in request.POST:
            messages.warning(request, "Os dados informados para o produto são inválidos.")
            return redirect("products:product_edit", product_id=product.pk)

        posted_unit_id = request.POST.get("unit")
        if posted_unit_id:
            get_object_or_404(Unit, id=posted_unit_id, company=company)

        forms_are_valid = form.is_valid()
        components_are_valid = component_formset.is_valid()
        if not forms_are_valid or not components_are_valid:
            return _render_product_form(
                request,
                company=company,
                form=form,
                component_formset=component_formset,
                product=product,
                submission_failed=True,
            )

        data = form.cleaned_data
        valid_component_count = sum(
            1
            for component_form in component_formset
            if component_form.cleaned_data
            and not component_form.cleaned_data.get("DELETE")
        )
        if (
            data["inventory_role"] == "prepared"
            and data.get("preparation_mode") == "on_demand"
            and valid_component_count == 0
        ):
            form.add_error(
                "preparation_mode",
                "Produto preparado sob demanda precisa de ao menos um componente.",
            )
        elif data["inventory_role"] != "prepared" and valid_component_count:
            form.add_error(
                "inventory_role",
                "Remova os ingredientes antes de alterar para um produto não preparado.",
            )

        if form.errors:
            return _render_product_form(
                request,
                company=company,
                form=form,
                component_formset=component_formset,
                product=product,
                submission_failed=True,
            )

        validation_target = form
        try:
            with transaction.atomic():
                locked_product = Product.objects.select_for_update().get(
                    pk=product.pk,
                    company=company,
                )
                locked_components = list(
                    ProductComponent.objects.select_for_update()
                    .filter(company=company, product=locked_product)
                    .order_by("id")
                )
                locked_by_id = {
                    component.pk: component for component in locked_components
                }
                if set(locked_by_id) != set(component_ids):
                    raise ValidationError(
                        "A receita mudou desde que a página foi aberta. "
                        "Recarregue e tente novamente."
                    )

                category_text = clean_category_name(data.get("category"))
                category = resolve_category(
                    company=company,
                    raw_name=category_text,
                )
                unit = _resolve_product_unit(company=company, data=data)
                _apply_product_data(
                    product=locked_product,
                    data=data,
                    category=category,
                    unit=unit,
                )
                locked_product.save()

                for component_form in component_formset:
                    component_data = component_form.cleaned_data
                    if not component_data:
                        continue

                    validation_target = component_form
                    component_id = component_data.get("component_id")
                    component = (
                        locked_by_id.get(component_id)
                        if component_id is not None
                        else None
                    )
                    if component_id is not None and component is None:
                        raise ValidationError(
                            "Um ingrediente informado não pertence a esta receita."
                        )
                    if component_data.get("DELETE"):
                        if component is not None:
                            component.delete()
                        continue
                    if component_data.get("ingredient") is None:
                        continue

                    if component is None:
                        component = ProductComponent(
                            company=company,
                            product=locked_product,
                        )
                    component.ingredient = component_data["ingredient"]
                    component.quantity = component_data["quantity"]
                    component.unit = component_data["unit"]
                    component.save()
        except ValidationError as error:
            _add_validation_error(validation_target, error)
            return _render_product_form(
                request,
                company=company,
                form=form,
                component_formset=component_formset,
                product=product,
                submission_failed=True,
            )

        messages.success(request, f"Produto atualizado: {locked_product.name}.")
        return redirect("products:product_edit", product_id=locked_product.pk)

    return _render_product_form(
        request,
        company=company,
        form=form,
        component_formset=component_formset,
        product=product,
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

    submitted_product_id = request.POST.get("product") if request.method == "POST" else None
    selected_product = None
    if request.method == "GET":
        selected_product = _query_selected_product(
            products,
            request.GET.get("produto"),
        )
    elif submitted_product_id not in (None, ""):
        try:
            int(submitted_product_id)
        except (TypeError, ValueError):
            selected_product = None
        else:
            selected_product = _query_selected_product(products, submitted_product_id)

    form = StockEntryForm(
        request.POST if request.method == "POST" else None,
        company=company,
        initial=(
            {"product": selected_product.pk}
            if selected_product is not None and request.method == "GET"
            else None
        ),
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
                entry_date=data.get("entry_date") or timezone.localdate(),
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
                    f"{format_quantity(entry.input_quantity, entry.input_unit)}. "
                    f"Custo total: {format_money(entry.total_cost)}."
                ),
            )
            return redirect("products:stock_dashboard")

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

    selected_product = None
    if request.method == "GET":
        selected_product = _query_selected_product(
            products,
            request.GET.get("produto"),
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
                f"{product.name}: ajuste positivo de "
                f"{format_quantity(result.difference, product.stock_base_unit)} aplicado.",
            )

            return redirect("products:stock_dashboard")

        quantity_to_remove = abs(result.difference)

        messages.warning(
            request,
            f"{product.name}: ajuste negativo de "
            f"{format_quantity(quantity_to_remove, product.stock_base_unit)} aplicado.",
        )

        return redirect("products:stock_dashboard")

    return render(
        request,
        "products/stock_count_form.html",
        {
            "products": products,
            "selected_product": selected_product,
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


def _production_rows(expanded_components, formset, *, show_requirements):
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
                "show_requirement": show_requirements,
                "sufficient": (
                    availability is not None
                    and availability.physical_stock >= component.total_quantity
                ),
            }
        )
    return rows


def _production_component_values(formset, expanded_components, form):
    component_values = {
        component_form.cleaned_data["component_id"]: {
            "actual_quantity": component_form.cleaned_data["actual_quantity"],
            "loss_quantity": component_form.cleaned_data["loss_quantity"],
        }
        for component_form in formset.forms
    }
    expected_ids = {
        component.source_component.pk for component in expanded_components
    }
    if set(component_values) != expected_ids:
        form.add_error(
            None,
            "Informe o consumo real de todos os ingredientes da produção.",
        )
        return None
    return component_values


def _estimate_production_cost(*, company, expanded_components, component_values):
    product_ids = [component.ingredient.pk for component in expanded_components]
    entries_by_product = {product_id: [] for product_id in product_ids}
    entries = StockEntry.objects.filter(
        company=company,
        product_id__in=product_ids,
        remaining_quantity__gt=0,
    ).order_by("product_id", "created_at", "id")
    for entry in entries:
        entries_by_product[entry.product_id].append(entry)

    total_cost = Decimal("0")
    for component in expanded_components:
        quantity = component_values[component.source_component.pk][
            "actual_quantity"
        ]
        total_cost += calculate_fifo_cost(
            product_id=component.ingredient.pk,
            quantity=quantity,
            entries=entries_by_product[component.ingredient.pk],
        )
    return total_cost


def _production_preview(form, expanded_components, component_values, estimated_cost):
    planned = form.cleaned_data["planned_quantity"]
    produced = form.cleaned_data["produced_quantity"]
    return {
        "planned_quantity": planned,
        "produced_quantity": produced,
        "yield_percentage": produced * Decimal("100") / planned,
        "expiration_date": form.cleaned_data.get("expiration_date"),
        "estimated_cost": estimated_cost,
        "components": [
            {
                "ingredient": component.ingredient,
                "quantity": component_values[component.source_component.pk][
                    "actual_quantity"
                ],
                "base_unit": component.base_unit,
            }
            for component in expanded_components
        ],
    }


def _production_confirmation_payload(*, company, user, product, form, component_values):
    expiration_date = form.cleaned_data.get("expiration_date")
    return {
        "company_id": company.pk,
        "user_id": user.pk,
        "product_id": product.pk,
        "planned_quantity": str(form.cleaned_data["planned_quantity"]),
        "produced_quantity": str(form.cleaned_data["produced_quantity"]),
        "production_date": form.cleaned_data["production_date"].isoformat(),
        "expiration_date": expiration_date.isoformat() if expiration_date else None,
        "notes": form.cleaned_data.get("notes") or "",
        "components": [
            {
                "component_id": component_id,
                "actual_quantity": str(values["actual_quantity"]),
                "loss_quantity": str(values["loss_quantity"]),
            }
            for component_id, values in sorted(component_values.items())
        ],
    }


def _valid_production_confirmation(token, payload):
    if not token:
        return False
    try:
        signed_payload = signing.loads(
            token,
            salt="products.production-preview",
            max_age=30 * 60,
        )
    except signing.BadSignature:
        return False
    return signed_payload == payload


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
        recipe_error = friendly_recipe_error(error)

    production_preview = None
    if request.method == "POST":
        form = ProductionForm(request.POST)
        formset = ProductionConsumptionFormSet(
            request.POST,
            prefix="consumption",
        )
        form_valid = form.is_valid()
        formset_valid = formset.is_valid()
        planned = form.cleaned_data.get("planned_quantity") if form_valid else None
        if planned is None:
            planned = parse_decimal(request.POST.get("planned_quantity"))
        expanded_components = ()
        if planned is not None and planned > 0 and recipe_error is None:
            try:
                expanded_components = expand_product_components(product, planned)
            except RecipeServiceError as error:
                recipe_error = friendly_recipe_error(error)
        rows = _production_rows(
            expanded_components,
            formset,
            show_requirements=planned is not None and planned > 0,
        )
        if form_valid and formset_valid and expanded_components and recipe_error is None:
            component_values = _production_component_values(
                formset,
                expanded_components,
                form,
            )
            if component_values is not None:
                insufficient_rows = []
                for row in rows:
                    actual = component_values[row["component"].source_component.pk][
                        "actual_quantity"
                    ]
                    row["actual_quantity"] = actual
                    row["sufficient"] = row["physical_stock"] >= actual
                    if not row["sufficient"]:
                        insufficient_rows.append(row)
                if insufficient_rows:
                    for row in insufficient_rows:
                        form.add_error(
                            None,
                            (
                                f"Estoque insuficiente de "
                                f"{row['component'].ingredient.name}: necessário "
                                f"{format_quantity(row['actual_quantity'], row['component'].base_unit)}, "
                                f"disponível {format_quantity(row['physical_stock'], row['component'].base_unit)}."
                            ),
                        )
                else:
                    try:
                        estimated_cost = _estimate_production_cost(
                            company=company,
                            expanded_components=expanded_components,
                            component_values=component_values,
                        )
                    except StockServiceError as error:
                        form.add_error(None, str(error))
                    else:
                        production_preview = _production_preview(
                            form,
                            expanded_components,
                            component_values,
                            estimated_cost,
                        )
                        confirmation_payload = _production_confirmation_payload(
                            company=company,
                            user=request.user,
                            product=product,
                            form=form,
                            component_values=component_values,
                        )
                        if request.POST.get("action") == "confirm":
                            if not _valid_production_confirmation(
                                request.POST.get("preview_token"),
                                confirmation_payload,
                            ):
                                form.add_error(
                                    None,
                                    "Revise o resumo novamente antes de registrar a produção.",
                                )
                                production_preview = None
                            else:
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
                                    message = (
                                        friendly_recipe_error(error)
                                        if isinstance(error, RecipeServiceError)
                                        else str(error)
                                    )
                                    form.add_error(None, message)
                                    production_preview = None
                                else:
                                    messages.success(
                                        request,
                                        "Produção registrada com sucesso.",
                                    )
                                    detail_url = reverse(
                                        "products:production_detail",
                                        args=[result.production.pk],
                                    )
                                    return redirect(f"{detail_url}?registrada=1")
                        else:
                            production_preview["confirmation_token"] = signing.dumps(
                                confirmation_payload,
                                salt="products.production-preview",
                                compress=True,
                            )
    else:
        form = ProductionForm(
            initial={
                "production_date": timezone.localdate(),
            }
        )
        expanded_components = ()
        if recipe_error is None:
            try:
                expanded_components = expand_product_components(
                    product,
                    Decimal("1"),
                )
            except RecipeServiceError as error:
                recipe_error = friendly_recipe_error(error)
        formset = ProductionConsumptionFormSet(
            initial=[
                {
                    "component_id": component.source_component.pk,
                    "actual_quantity": None,
                    "loss_quantity": "0",
                }
                for component in expanded_components
            ],
            prefix="consumption",
        )
        rows = _production_rows(
            expanded_components,
            formset,
            show_requirements=False,
        )

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
            "production_preview": production_preview,
        },
    )


@login_required
@company_required
def production_list(request):
    if not can_view_stock(request.user):
        messages.warning(request, "Você não tem permissão para ver produções.")
        return redirect("orders:pdv")
    productions = Production.objects.filter(company=request.current_company)
    selected_product = _query_selected_product(
        Product.objects.filter(
            company=request.current_company,
            active=True,
            inventory_role="prepared",
            preparation_mode="pre_portioned",
        ),
        request.GET.get("produto"),
    )
    if selected_product is not None:
        productions = productions.filter(product=selected_product)
    productions = (
        productions
        .select_related("product", "created_by", "reversed_by")
        .order_by("-production_date", "-id")
    )
    return render(
        request,
        "products/production_list.html",
        {
            "productions": productions,
            "selected_product": selected_product,
        },
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
            "production_registered": request.GET.get("registrada") == "1",
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
