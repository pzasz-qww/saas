from collections import Counter, defaultdict
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from products.services import (
    aggregate_product_quantities,
    consume_stock,
    lock_fifo_entries,
    restore_sale_stock,
)
from products.models import StockMovement
from sales.models import Sale, SaleItem

from .models import Order


class OrderServiceError(Exception):
    """Base exception for safe order state transitions."""


class InvalidOrderState(OrderServiceError):
    pass


class InvalidOrderData(OrderServiceError):
    pass


class InvalidPaymentMethod(OrderServiceError):
    pass


class ConcurrentOrderUpdate(OrderServiceError):
    pass


@dataclass(frozen=True)
class ApprovalResult:
    sale: Sale
    created: bool


@dataclass(frozen=True)
class CancellationResult:
    order: Order
    restored: bool


@dataclass(frozen=True)
class StateTransitionResult:
    order: Order
    changed: bool


def _validate_payment_method(payment_method):
    valid_payment_methods = {value for value, _label in Sale.PAYMENT_METHODS}

    if payment_method not in valid_payment_methods:
        raise InvalidPaymentMethod("Forma de pagamento inválida.")


def _validate_order_items(order, items):
    if not items:
        raise InvalidOrderData("O pedido não possui itens para aprovação.")

    for item in items:
        if item.company_id != order.company_id:
            raise InvalidOrderData("Um item pertence a outra empresa.")

        if item.product.company_id != order.company_id:
            raise InvalidOrderData("Um produto pertence a outra empresa.")

        if item.quantity <= 0:
            raise InvalidOrderData("Todos os itens devem possuir quantidade positiva.")

        if item.unit_price < 0:
            raise InvalidOrderData("O preço pactuado não pode ser negativo.")


def _get_traceable_approved_sale(order):
    """Return an approved sale only when its items and stock exits are complete."""

    sale = Sale.objects.select_for_update().get(
        pk=order.sale_id,
        company=order.company,
    )
    if sale.status != "active":
        raise InvalidOrderState(
            "O pedido aprovado possui uma venda em estado incompatível."
        )

    order_items = list(
        order.items.select_for_update()
        .select_related("product")
        .order_by("product_id", "id")
    )
    _validate_order_items(order, order_items)

    sale_items = list(
        sale.items.select_for_update()
        .select_related("product")
        .order_by("product_id", "id")
    )
    if not sale_items:
        raise InvalidOrderState(
            "O pedido aprovado possui uma venda legada ou incompleta."
        )

    for item in sale_items:
        if (
            item.company_id != order.company_id
            or item.product.company_id != order.company_id
            or item.quantity <= 0
            or item.unit_price < 0
        ):
            raise InvalidOrderState(
                "O pedido aprovado possui itens de venda inconsistentes."
            )

    order_lines = Counter(
        (item.product_id, item.quantity, item.unit_price)
        for item in order_items
    )
    sale_lines = Counter(
        (item.product_id, item.quantity, item.unit_price)
        for item in sale_items
    )
    if order_lines != sale_lines:
        raise InvalidOrderState(
            "O pedido aprovado e a venda vinculada possuem itens divergentes."
        )

    sale_item_by_id = {item.pk: item for item in sale_items}
    movements = list(
        StockMovement.objects.select_for_update()
        .filter(
            sale_item_id__in=sale_item_by_id,
            movement_type="sale",
        )
        .order_by("product_id", "stock_entry_id", "id")
    )
    quantities_by_item = defaultdict(int)
    for movement in movements:
        sale_item = sale_item_by_id[movement.sale_item_id]
        if (
            movement.company_id != order.company_id
            or movement.product_id != sale_item.product_id
            or movement.stock_entry_id is None
            or movement.quantity <= 0
        ):
            raise InvalidOrderState(
                "O pedido aprovado possui baixa de estoque inconsistente."
            )
        quantities_by_item[sale_item.pk] += movement.quantity

    if any(
        quantities_by_item[item.pk] != item.quantity
        for item in sale_items
    ):
        raise InvalidOrderState(
            "O pedido aprovado possui venda legada ou baixa incompleta."
        )

    movement_ids = [movement.pk for movement in movements]
    if StockMovement.objects.filter(reversal_of_id__in=movement_ids).exists():
        raise InvalidOrderState(
            "O pedido aprovado possui baixa já revertida."
        )

    return sale


def mark_order_delivered(*, order_id, company):
    """Mark a sold order as delivered while serializing state transitions."""

    with transaction.atomic():
        order = (
            Order.objects
            .select_for_update()
            .get(pk=order_id, company=company)
        )

        if order.status != "sold":
            return StateTransitionResult(order=order, changed=False)

        order.status = "delivered"
        order.delivered_at = timezone.now()
        order.save(update_fields=["status", "delivered_at"])
        return StateTransitionResult(order=order, changed=True)


def cancel_pre_sale_order(*, order_id, company):
    """Cancel a pre-sale without touching stock."""

    with transaction.atomic():
        order = (
            Order.objects
            .select_for_update()
            .get(pk=order_id, company=company)
        )

        if order.status != "pre_sale":
            return StateTransitionResult(order=order, changed=False)

        order.status = "cancelled"
        order.save(update_fields=["status"])
        return StateTransitionResult(order=order, changed=True)


def discard_paid_order(*, order_id, company, user=None):
    """Discard a sold order without returning its allocated stock."""

    del user  # Reserved for a future audit trail without changing the API.

    with transaction.atomic():
        order = (
            Order.objects
            .select_for_update()
            .get(pk=order_id, company=company)
        )

        if order.status not in {"sold", "delivered"}:
            return StateTransitionResult(order=order, changed=False)

        if order.sale_id:
            sale = Sale.objects.select_for_update().get(
                pk=order.sale_id,
                company=order.company,
            )
            sale.status = "discarded"
            sale.save(update_fields=["status"])

        order.status = "discarded"
        order.save(update_fields=["status"])
        return StateTransitionResult(order=order, changed=True)


def approve_order(*, order_id, company, payment_method, user=None):
    """Approve one order and consume all stock as a single transaction."""

    _validate_payment_method(payment_method)

    try:
        with transaction.atomic():
            order = (
                Order.objects
                .select_for_update()
                .get(pk=order_id, company=company)
            )

            if order.status in {"sold", "delivered"}:
                if not order.sale_id:
                    raise InvalidOrderState(
                        "O pedido está aprovado, mas não possui uma venda vinculada."
                    )

                sale = _get_traceable_approved_sale(order)
                return ApprovalResult(sale=sale, created=False)

            if order.status != "pre_sale" or order.sale_id is not None:
                raise InvalidOrderState(
                    "Somente pedidos em pré-venda podem ser aprovados."
                )

            items = list(
                order.items
                .select_for_update()
                .select_related("product")
                .order_by("product_id", "id")
            )
            _validate_order_items(order, items)

            product_quantities = aggregate_product_quantities(
                items,
                company=order.company,
            )
            entries_by_product = lock_fifo_entries(
                company=order.company,
                product_quantities=product_quantities,
            )

            sale = Sale.objects.create(
                company=order.company,
                payment_method=payment_method,
                created_by=user,
            )

            for order_item in items:
                sale_item = SaleItem.objects.create(
                    sale=sale,
                    company=order.company,
                    product=order_item.product,
                    quantity=order_item.quantity,
                    unit_price=order_item.unit_price,
                    unit_cost=0,
                )
                movements = consume_stock(
                    company=order.company,
                    sale_item=sale_item,
                    quantity=order_item.quantity,
                    entries_by_product=entries_by_product,
                    created_by=user,
                )
                total_cost = sum(
                    (movement.cost_value for movement in movements),
                    start=order_item.quantity * 0,
                )
                sale_item.unit_cost = total_cost / order_item.quantity
                sale_item.save(
                    update_fields=["unit_cost", "total_price", "total_cost"]
                )

            sale.recalculate_totals()

            updated = Order.objects.filter(
                pk=order.pk,
                company=order.company,
                status="pre_sale",
                sale__isnull=True,
            ).update(
                status="sold",
                approved_by=user,
                approved_at=timezone.now(),
                sale=sale,
            )

            if updated != 1:
                raise ConcurrentOrderUpdate(
                    "O pedido foi alterado durante a aprovação."
                )

            order.refresh_from_db()
            return ApprovalResult(sale=sale, created=True)
    except ConcurrentOrderUpdate:
        current_order = Order.objects.filter(
            pk=order_id,
            company=company,
        ).first()

        if (
            current_order
            and current_order.status in {"sold", "delivered"}
            and current_order.sale_id
        ):
            return ApprovalResult(
                sale=Sale.objects.get(
                    pk=current_order.sale_id,
                    company=current_order.company,
                ),
                created=False,
            )

        raise


def cancel_paid_order_with_stock_return(*, order_id, company, user=None):
    """Cancel a paid order and restore every original FIFO allocation."""

    with transaction.atomic():
        order = (
            Order.objects
            .select_for_update()
            .get(pk=order_id, company=company)
        )

        if order.status == "cancelled":
            if not order.sale_id:
                raise InvalidOrderState(
                    "O pedido está cancelado, mas não possui uma venda vinculada."
                )

            sale = Sale.objects.select_for_update().get(
                pk=order.sale_id,
                company=order.company,
            )

            if sale.status != "cancelled":
                raise InvalidOrderState(
                    "O pedido está cancelado, mas a venda vinculada não está."
                )

            return CancellationResult(order=order, restored=False)

        if order.status not in {"sold", "delivered"}:
            raise InvalidOrderState(
                "Somente pedidos vendidos ou entregues podem retornar ao estoque."
            )

        if not order.sale_id:
            raise InvalidOrderState(
                "O pedido não possui uma venda vinculada para cancelamento."
            )

        sale = Sale.objects.select_for_update().get(
            pk=order.sale_id,
            company=order.company,
        )

        restore_sale_stock(
            company=order.company,
            sale=sale,
            created_by=user,
        )

        sale.status = "cancelled"
        sale.save(update_fields=["status"])

        updated = Order.objects.filter(
            pk=order.pk,
            company=order.company,
            status__in=["sold", "delivered"],
            sale=sale,
        ).update(status="cancelled")

        if updated != 1:
            raise ConcurrentOrderUpdate(
                "O pedido foi alterado durante o cancelamento."
            )

        order.refresh_from_db()
        return CancellationResult(order=order, restored=True)
