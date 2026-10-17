"""Read-only boundary with the stable operational apps."""
from collections import Counter
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError

from .models import ItemPrintContext, OrderPrintContext


def build_snapshot(order, *, timezone_name="America/Sao_Paulo", using="default"):
    if order.status not in {"sold", "delivered"} or not order.sale_id:
        raise ValidationError("Somente pedidos com venda confirmada podem gerar um ticket.")
    sale = order.sale
    if sale.company_id != order.company_id or sale.status != "active":
        raise ValidationError("Venda incompatível com o pedido.")
    items = list(order.items.using(using).select_related("product").order_by("pk"))
    sale_items = list(sale.items.using(using).all())
    if not items or any(i.company_id != order.company_id or i.product.company_id != order.company_id for i in items):
        raise ValidationError("Itens do pedido inconsistentes.")
    if any(i.company_id != order.company_id for i in sale_items):
        raise ValidationError("Itens da venda inconsistentes.")
    def signature(item):
        return item.product_id, item.quantity, item.unit_price, item.total_price
    if Counter(map(signature, items)) != Counter(map(signature, sale_items)):
        raise ValidationError("Pedido e venda possuem valores divergentes.")
    if sum((i.total_price for i in items), Decimal(0)) != sale.total_amount or order.total_amount != sale.total_amount:
        raise ValidationError("Totais persistidos divergentes.")
    context = OrderPrintContext.objects.using(using).filter(company_id=order.company_id, order_reference=order.pk).first()
    names = {(item_id, product_id): name for item_id, product_id, name in ItemPrintContext.objects.using(using).filter(company_id=order.company_id, order_reference=order.pk).values_list("item_reference", "product_reference", "product_name")}
    missing = []
    if context is None:
        missing.append("employee_identity_at_order_creation")
    if any((item.pk, item.product_id) not in names for item in items):
        missing.append("product_name_at_order_creation")
    return {
        "schema_version": 1,
        "company_name": order.company.name,
        "order_number": order.pk,
        "sale_reference": sale.pk,
        "ordered_at": order.created_at.astimezone(ZoneInfo(timezone_name)).isoformat(),
        "table": order.table_or_tab or "",
        "employee_role": context.employee_role if context else "Cargo não registrado",
        "employee_name": context.employee_name if context else "Não registrado",
        "items": [{
            "quantity": str(item.quantity),
            "name": names.get((item.pk, item.product_id), item.product.name),
            "name_source": "order_item_capture" if (item.pk, item.product_id) in names else "snapshot_creation",
            "observation": item.notes or "",
            "unit_price": str(item.unit_price),
            "line_total": str(item.total_price),
        } for item in items],
        "observation": order.notes or "",
        "total": str(sale.total_amount),
        "payment_method": sale.get_payment_method_display().upper(),
        "payment_code": sale.payment_method,
        "missing_historical_data": missing,
    }
