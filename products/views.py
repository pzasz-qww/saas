from io import BytesIO
from decimal import Decimal, InvalidOperation
from xml.sax.saxutils import escape

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET
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


def stock_report_products_for_company(company):
    return (
        Product.objects
        .filter(company=company, active=True)
        .select_related("unit")
        .annotate(
            report_current_stock=Coalesce(
                Sum(
                    "stock_entries__remaining_quantity",
                    filter=Q(stock_entries__company=company),
                ),
                Value(Decimal("0.00")),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            )
        )
        .order_by("category", "name")
    )


@login_required
@company_required
def stock_dashboard(request):
    if not can_view_stock(request.user):
        messages.warning(request, "Você não tem permissão para ver o estoque.")
        return redirect("orders:pdv")

    company = request.current_company

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
@company_required
@require_GET
def stock_report_pdf(request):
    if not can_view_stock(request.user):
        messages.warning(request, "Você não tem permissão para ver o estoque.")
        return redirect("orders:pdv")

    company = request.current_company

    products = stock_report_products_for_company(company)

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
        "Estoque mínimo",
        "Status",
        "Preço de venda",
    ]]

    for product in products:
        current_stock = product.report_current_stock

        if current_stock <= 0:
            status = "Esgotado"
        elif current_stock <= product.minimum_quantity:
            status = "Baixo"
        else:
            status = "Disponível"

        minimum_stock = (
            f"{product.minimum_quantity:.2f}".replace(".", ",")
            if product.minimum_quantity > 0
            else "-"
        )

        table_data.append([
            Paragraph(escape(product.name), cell_style),
            Paragraph(escape(product.category or "Sem categoria"), cell_style),
            escape(product.unit.symbol),
            f"{current_stock:.2f}".replace(".", ","),
            minimum_stock,
            status,
            f"R$ {product.sale_price:.2f}".replace(".", ","),
        ])

    table = Table(
        table_data,
        colWidths=[58 * mm, 38 * mm, 24 * mm, 30 * mm, 30 * mm, 29 * mm, 34 * mm],
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


@login_required
@company_required
def product_create(request):
    if not can_create_stock_entry(request.user):
        messages.warning(request, "Você não tem permissão para cadastrar produtos.")
        return redirect("products:stock_dashboard")

    company = request.current_company

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
@company_required
def stock_entry_create(request):
    if not can_create_stock_entry(request.user):
        messages.warning(request, "Você não tem permissão para inserir estoque.")
        return redirect("products:stock_dashboard")

    company = request.current_company

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
@company_required
def stock_count_adjust(request):
    if not can_adjust_stock(request.user):
        messages.warning(request, "Você não tem permissão para fazer conferência de estoque.")
        return redirect("products:stock_dashboard")

    company = request.current_company

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
