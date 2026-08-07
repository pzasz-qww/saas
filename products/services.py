from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import F, Sum

from .models import Product, StockEntry, StockMovement


ZERO = Decimal("0.00")


class StockServiceError(Exception):
    """Base exception for stock operations that must be rolled back."""


class InvalidStockOperation(StockServiceError):
    """Raised when an operation violates a stock invariant."""


class InsufficientStock(StockServiceError):
    def __init__(self, *, product_id, requested, available):
        self.product_id = product_id
        self.requested = requested
        self.available = available
        super().__init__(
            f"Estoque insuficiente para o produto #{product_id}: "
            f"solicitado {requested}, disponível {available}."
        )


class StockConcurrencyError(StockServiceError):
    """Raised when locked/planned stock changed before its guarded update."""


class UntraceableSaleStock(StockServiceError):
    """Raised when a sale cannot be safely restored to its original entries."""


@dataclass(frozen=True)
class StockShortage:
    product_id: int
    requested: Decimal
    available: Decimal


def _company_id(company):
    company_id = getattr(company, "pk", company)
    if company_id is None:
        raise InvalidStockOperation("A empresa precisa estar salva.")
    return company_id


def _positive_decimal(value, *, field_name="quantidade"):
    if isinstance(value, bool):
        raise InvalidStockOperation(f"{field_name.capitalize()} inválida.")

    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise InvalidStockOperation(
            f"{field_name.capitalize()} inválida."
        ) from None

    if not parsed.is_finite() or parsed <= ZERO:
        raise InvalidStockOperation(f"{field_name.capitalize()} deve ser positiva.")

    return parsed


def _nonnegative_decimal(value, *, field_name="valor"):
    if isinstance(value, bool):
        raise InvalidStockOperation(f"{field_name.capitalize()} inválido.")

    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise InvalidStockOperation(
            f"{field_name.capitalize()} inválido."
        ) from None

    if not parsed.is_finite() or parsed < ZERO:
        raise InvalidStockOperation(
            f"{field_name.capitalize()} não pode ser negativo."
        )

    return parsed


def _require_atomic_transaction():
    if not transaction.get_connection().in_atomic_block:
        raise InvalidStockOperation(
            "A operação de estoque precisa ocorrer dentro de transaction.atomic()."
        )


def _normalize_product_quantities(product_quantities):
    normalized = defaultdict(lambda: ZERO)

    for product, quantity in product_quantities.items():
        product_id = getattr(product, "pk", product)
        if product_id is None:
            raise InvalidStockOperation("Produto sem identificador.")

        normalized[product_id] += _positive_decimal(quantity)

    if not normalized:
        raise InvalidStockOperation("A operação precisa possuir ao menos um produto.")

    return dict(sorted(normalized.items()))


def _entry_sort_key(entry):
    if entry.pk is None or entry.created_at is None:
        raise InvalidStockOperation("Entrada de estoque ainda não contabilizada.")
    return entry.product_id, entry.created_at, entry.pk


def _get_company_product(*, company_id, product):
    product_id = getattr(product, "pk", product)
    if product_id is None:
        raise InvalidStockOperation("Produto sem identificador.")

    try:
        return Product.objects.get(pk=product_id, company_id=company_id)
    except Product.DoesNotExist:
        raise InvalidStockOperation(
            f"O produto #{product_id} não pertence à empresa informada."
        ) from None


def _validate_company_product_ids(*, company_id, product_ids):
    company_product_ids = set(
        Product.objects.filter(
            company_id=company_id,
            pk__in=product_ids,
        ).values_list("pk", flat=True)
    )
    invalid_product_ids = sorted(set(product_ids) - company_product_ids)
    if invalid_product_ids:
        invalid_ids = ", ".join(str(product_id) for product_id in invalid_product_ids)
        raise InvalidStockOperation(
            f"Produto(s) fora da empresa informada: {invalid_ids}."
        )


def get_stock_shortages(*, company, product_quantities):
    """Return current shortages without locking or changing stock.

    This is an early availability check only. Callers that consume stock must
    revalidate inside their own transaction after acquiring row locks.
    """
    company_id = _company_id(company)
    normalized = _normalize_product_quantities(product_quantities)
    product_ids = list(normalized)
    _validate_company_product_ids(
        company_id=company_id,
        product_ids=product_ids,
    )

    available_by_product = dict(
        StockEntry.objects.filter(
            company_id=company_id,
            product_id__in=product_ids,
            remaining_quantity__gt=ZERO,
        )
        .values("product_id")
        .annotate(total=Sum("remaining_quantity"))
        .values_list("product_id", "total")
    )

    shortages = []
    for product_id, requested in normalized.items():
        available = available_by_product.get(product_id, ZERO) or ZERO
        if available < requested:
            shortages.append(
                StockShortage(
                    product_id=product_id,
                    requested=requested,
                    available=available,
                )
            )

    return shortages


def aggregate_product_quantities(items, *, company):
    """Validate company ownership and aggregate item quantities by product."""
    company_id = _company_id(company)
    totals = defaultdict(lambda: ZERO)

    for item in items:
        product_id = getattr(item, "product_id", None)
        if product_id is None:
            raise InvalidStockOperation("Item sem produto.")

        if getattr(item, "company_id", None) != company_id:
            raise InvalidStockOperation(
                f"O item do produto #{product_id} pertence a outra empresa."
            )

        product = getattr(item, "product", None)
        if product is None or product.company_id != company_id:
            raise InvalidStockOperation(
                f"O produto #{product_id} pertence a outra empresa."
            )

        totals[product_id] += _positive_decimal(item.quantity)

    if not totals:
        raise InvalidStockOperation("O pedido não possui itens.")

    return dict(sorted(totals.items()))


def lock_fifo_entries(*, company, product_quantities):
    """
    Lock all usable entries for the requested products in deterministic FIFO order.

    The caller must keep the surrounding transaction open while consuming the
    returned instances. The returned lists are intentionally mutable: successive
    SaleItems for the same product share the updated in-memory balances.
    """
    _require_atomic_transaction()
    company_id = _company_id(company)
    normalized = _normalize_product_quantities(product_quantities)
    product_ids = list(normalized)

    _validate_company_product_ids(
        company_id=company_id,
        product_ids=product_ids,
    )

    entries = list(
        StockEntry.objects.select_for_update()
        .filter(
            company_id=company_id,
            product_id__in=product_ids,
            remaining_quantity__gt=ZERO,
        )
        .order_by("product_id", "created_at", "id")
    )

    entries_by_product = {product_id: [] for product_id in product_ids}
    for entry in entries:
        entries_by_product[entry.product_id].append(entry)

    validate_stock_availability(
        product_quantities=normalized,
        entries_by_product=entries_by_product,
    )
    return entries_by_product


def validate_stock_availability(*, product_quantities, entries_by_product):
    """Validate aggregate availability from already selected/locked entries."""
    normalized = _normalize_product_quantities(product_quantities)
    seen_entry_ids = set()

    for product_id, requested in normalized.items():
        entries = list(entries_by_product.get(product_id, ()))
        if entries != sorted(entries, key=_entry_sort_key):
            raise InvalidStockOperation(
                "As entradas precisam estar em ordem FIFO determinística."
            )

        available = ZERO
        company_ids = set()

        for entry in entries:
            if entry.pk in seen_entry_ids:
                raise InvalidStockOperation(
                    f"A entrada #{entry.pk} foi informada mais de uma vez."
                )
            seen_entry_ids.add(entry.pk)

            if entry.product_id != product_id:
                raise InvalidStockOperation(
                    f"A entrada #{entry.pk} não pertence ao produto #{product_id}."
                )

            company_ids.add(entry.company_id)
            available += _nonnegative_decimal(
                entry.remaining_quantity,
                field_name=f"saldo da entrada #{entry.pk}",
            )

        if len(company_ids) > 1:
            raise InvalidStockOperation(
                f"Entradas de empresas diferentes para o produto #{product_id}."
            )

        if available < requested:
            raise InsufficientStock(
                product_id=product_id,
                requested=requested,
                available=available,
            )


def _create_negative_movements(
    *,
    company_id,
    product_id,
    quantity,
    entries,
    movement_type,
    created_by,
    reason,
    notes,
    sale_item=None,
):
    requested = _positive_decimal(quantity)
    validate_stock_availability(
        product_quantities={product_id: requested},
        entries_by_product={product_id: entries},
    )

    remaining_to_consume = requested
    allocations = []

    for entry in entries:
        if remaining_to_consume <= ZERO:
            break

        available = _nonnegative_decimal(
            entry.remaining_quantity,
            field_name=f"saldo da entrada #{entry.pk}",
        )
        quantity_from_entry = min(available, remaining_to_consume)
        if quantity_from_entry <= ZERO:
            continue

        allocations.append((entry, quantity_from_entry))
        remaining_to_consume -= quantity_from_entry

    if remaining_to_consume > ZERO:
        raise InsufficientStock(
            product_id=product_id,
            requested=requested,
            available=requested - remaining_to_consume,
        )

    movements = []
    for entry, allocated_quantity in allocations:
        if entry.company_id != company_id or entry.product_id != product_id:
            raise InvalidStockOperation(
                f"A entrada #{entry.pk} não pertence à empresa e ao produto esperados."
            )

        updated = (
            StockEntry.objects.filter(
                pk=entry.pk,
                company_id=company_id,
                product_id=product_id,
                remaining_quantity__gte=allocated_quantity,
            )
            .update(
                remaining_quantity=F("remaining_quantity") - allocated_quantity,
            )
        )
        if updated != 1:
            raise StockConcurrencyError(
                f"O saldo da entrada #{entry.pk} mudou durante a operação."
            )

        entry.remaining_quantity -= allocated_quantity

        sale_value = ZERO
        if movement_type == "sale":
            if sale_item is None:
                raise InvalidStockOperation(
                    "Movimentos de venda precisam estar ligados a um item da venda."
                )
            sale_value = allocated_quantity * sale_item.unit_price

        movements.append(
            StockMovement.objects.create(
                company_id=company_id,
                product_id=product_id,
                stock_entry=entry,
                sale_item=sale_item,
                movement_type=movement_type,
                quantity=allocated_quantity,
                sale_value=sale_value,
                cost_value=allocated_quantity * entry.unit_cost,
                reason=reason,
                notes=notes,
                created_by=created_by,
            )
        )

    return movements


def consume_stock(
    *,
    company,
    sale_item,
    entries_by_product,
    quantity=None,
    created_by=None,
):
    """Consume FIFO stock for one saved SaleItem and create one movement per entry."""
    _require_atomic_transaction()
    company_id = _company_id(company)

    if getattr(sale_item, "pk", None) is None:
        raise InvalidStockOperation("O item da venda precisa estar salvo.")

    try:
        locked_sale_item = (
            sale_item.__class__.objects.select_for_update()
            .select_related("sale", "product")
            .get(pk=sale_item.pk)
        )
    except sale_item.__class__.DoesNotExist:
        raise InvalidStockOperation("Item da venda inexistente.") from None

    product_id = locked_sale_item.product_id
    if (
        locked_sale_item.company_id != company_id
        or locked_sale_item.sale.company_id != company_id
        or locked_sale_item.product.company_id != company_id
    ):
        raise InvalidStockOperation(
            "Venda, item e produto precisam pertencer à mesma empresa."
        )

    item_quantity = _positive_decimal(locked_sale_item.quantity)
    requested = item_quantity if quantity is None else _positive_decimal(quantity)
    if requested != item_quantity:
        raise InvalidStockOperation(
            "A quantidade consumida precisa ser igual à quantidade do item da venda."
        )

    existing_movements = list(
        StockMovement.objects.select_for_update()
        .filter(
            sale_item_id=locked_sale_item.pk,
            movement_type="sale",
        )
        .order_by("stock_entry_id", "id")
    )
    if existing_movements:
        existing_quantity = sum(
            (movement.quantity for movement in existing_movements),
            ZERO,
        )
        if existing_quantity != requested or any(
            movement.company_id != company_id
            or movement.product_id != product_id
            or movement.stock_entry_id is None
            for movement in existing_movements
        ):
            raise UntraceableSaleStock(
                f"Os movimentos existentes do item #{locked_sale_item.pk} são inconsistentes."
            )
        return existing_movements

    entries = entries_by_product.get(product_id, [])
    return _create_negative_movements(
        company_id=company_id,
        product_id=product_id,
        quantity=requested,
        entries=entries,
        movement_type="sale",
        sale_item=locked_sale_item,
        created_by=created_by,
        reason=f"Venda #{locked_sale_item.sale_id}",
        notes=None,
    )


@transaction.atomic
def restore_sale_stock(*, company, sale, created_by=None):
    """Restore every traceable sale movement to its original StockEntry."""
    company_id = _company_id(company)
    if getattr(sale, "pk", None) is None:
        raise InvalidStockOperation("A venda precisa estar salva.")

    try:
        locked_sale = sale.__class__.objects.select_for_update().get(pk=sale.pk)
    except sale.__class__.DoesNotExist:
        raise InvalidStockOperation("Venda inexistente.") from None

    if locked_sale.company_id != company_id:
        raise InvalidStockOperation("A venda pertence a outra empresa.")

    sale_items = list(
        locked_sale.items.select_for_update()
        .select_related("product")
        .order_by("product_id", "id")
    )
    if not sale_items:
        raise UntraceableSaleStock("A venda não possui itens rastreáveis.")

    item_by_id = {}
    for item in sale_items:
        if (
            item.company_id != company_id
            or item.product.company_id != company_id
        ):
            raise InvalidStockOperation(
                "Venda, itens e produtos precisam pertencer à mesma empresa."
            )
        _positive_decimal(item.quantity)
        item_by_id[item.pk] = item

    item_ids = list(item_by_id)
    outbound_movements = list(
        StockMovement.objects.select_for_update()
        .filter(
            sale_item_id__in=item_ids,
            movement_type="sale",
        )
        .order_by("product_id", "stock_entry_id", "id")
    )

    if StockMovement.objects.filter(
        sale_item_id__in=item_ids,
        movement_type="return_to_stock",
        reversal_of__isnull=True,
    ).exists():
        raise UntraceableSaleStock(
            "A venda possui retorno sem vínculo com o movimento original."
        )

    totals_by_item = defaultdict(lambda: ZERO)
    for movement in outbound_movements:
        item = item_by_id[movement.sale_item_id]
        movement_quantity = _positive_decimal(movement.quantity)
        if (
            movement.company_id != company_id
            or movement.product_id != item.product_id
            or movement.stock_entry_id is None
        ):
            raise UntraceableSaleStock(
                f"O movimento #{movement.pk} não possui rastreabilidade suficiente."
            )
        totals_by_item[item.pk] += movement_quantity

    for item in sale_items:
        if totals_by_item[item.pk] != item.quantity:
            raise UntraceableSaleStock(
                f"O item de venda #{item.pk} é legado ou possui baixa incompleta."
            )

    movement_by_id = {movement.pk: movement for movement in outbound_movements}
    reversals = list(
        StockMovement.objects.select_for_update()
        .filter(reversal_of_id__in=movement_by_id)
        .order_by("reversal_of_id")
    )
    reversal_by_original_id = {
        reversal.reversal_of_id: reversal for reversal in reversals
    }

    if reversal_by_original_id:
        if len(reversal_by_original_id) != len(outbound_movements):
            raise UntraceableSaleStock("A venda possui retorno parcial inconsistente.")

        for original_id, reversal in reversal_by_original_id.items():
            original = movement_by_id[original_id]
            if (
                reversal.movement_type != "return_to_stock"
                or reversal.company_id != company_id
                or reversal.product_id != original.product_id
                or reversal.stock_entry_id != original.stock_entry_id
                or reversal.sale_item_id != original.sale_item_id
                or reversal.quantity != original.quantity
            ):
                raise UntraceableSaleStock(
                    f"O retorno do movimento #{original_id} é inconsistente."
                )
        return reversals

    entry_ids = {movement.stock_entry_id for movement in outbound_movements}
    entries = list(
        StockEntry.objects.select_for_update()
        .filter(pk__in=entry_ids)
        .order_by("product_id", "created_at", "id")
    )
    entry_by_id = {entry.pk: entry for entry in entries}
    if set(entry_by_id) != entry_ids:
        raise UntraceableSaleStock("Uma entrada original da venda não existe mais.")

    for movement in outbound_movements:
        entry = entry_by_id[movement.stock_entry_id]
        if (
            entry.company_id != company_id
            or entry.product_id != movement.product_id
        ):
            raise InvalidStockOperation(
                f"A entrada #{entry.pk} não pertence à empresa e ao produto esperados."
            )
        _nonnegative_decimal(
            entry.remaining_quantity,
            field_name=f"saldo da entrada #{entry.pk}",
        )

    ordered_movements = sorted(
        outbound_movements,
        key=lambda movement: (
            _entry_sort_key(entry_by_id[movement.stock_entry_id]),
            movement.pk,
        ),
    )

    return_movements = []
    for original in ordered_movements:
        entry = entry_by_id[original.stock_entry_id]
        updated = (
            StockEntry.objects.filter(
                pk=entry.pk,
                company_id=company_id,
                product_id=original.product_id,
                remaining_quantity__isnull=False,
            )
            .update(
                remaining_quantity=F("remaining_quantity") + original.quantity,
            )
        )
        if updated != 1:
            raise StockConcurrencyError(
                f"Não foi possível restaurar a entrada #{entry.pk}."
            )

        entry.remaining_quantity += original.quantity
        cost_value = original.cost_value
        if cost_value is None:
            cost_value = original.quantity * entry.unit_cost

        return_movements.append(
            StockMovement.objects.create(
                company_id=company_id,
                product_id=original.product_id,
                stock_entry=entry,
                sale_item_id=original.sale_item_id,
                reversal_of=original,
                movement_type="return_to_stock",
                quantity=original.quantity,
                sale_value=ZERO,
                cost_value=cost_value,
                reason=f"Retorno da venda #{locked_sale.pk}",
                notes=f"Reversão do movimento de saída #{original.pk}.",
                created_by=created_by,
            )
        )

    return return_movements


@transaction.atomic
def apply_positive_adjustment(
    *,
    company,
    product,
    quantity,
    cost_value=None,
    reason="Ajuste positivo de estoque",
    notes=None,
    created_by=None,
):
    """Create an explicit entry and its positive adjustment movement."""
    company_id = _company_id(company)
    product = _get_company_product(company_id=company_id, product=product)
    quantity = _positive_decimal(quantity)

    if cost_value is None:
        cost_value = quantity * product.average_cost
    cost_value = _nonnegative_decimal(cost_value, field_name="custo do ajuste")

    entry = StockEntry.objects.create(
        company_id=company_id,
        product=product,
        entry_mode="simple",
        total_cost=cost_value,
        quantity_added=quantity,
        remaining_quantity=quantity,
        notes=f"Entrada criada por ajuste positivo. {notes or ''}".strip(),
        created_by=created_by,
    )

    return StockMovement.objects.create(
        company_id=company_id,
        product=product,
        stock_entry=entry,
        movement_type="adjustment_positive",
        quantity=quantity,
        sale_value=ZERO,
        cost_value=cost_value,
        reason=reason,
        notes=notes,
        created_by=created_by,
    )


@transaction.atomic
def apply_negative_adjustment(
    *,
    company,
    product,
    quantity,
    reason="Ajuste negativo de estoque",
    notes=None,
    created_by=None,
):
    """Consume FIFO entries explicitly for a negative stock adjustment."""
    company_id = _company_id(company)
    product = _get_company_product(company_id=company_id, product=product)
    quantity = _positive_decimal(quantity)
    entries_by_product = lock_fifo_entries(
        company=company_id,
        product_quantities={product.pk: quantity},
    )

    return _create_negative_movements(
        company_id=company_id,
        product_id=product.pk,
        quantity=quantity,
        entries=entries_by_product[product.pk],
        movement_type="adjustment_negative",
        created_by=created_by,
        reason=reason,
        notes=notes,
    )


__all__ = [
    "InsufficientStock",
    "InvalidStockOperation",
    "StockConcurrencyError",
    "StockServiceError",
    "StockShortage",
    "UntraceableSaleStock",
    "aggregate_product_quantities",
    "apply_negative_adjustment",
    "apply_positive_adjustment",
    "consume_stock",
    "get_stock_shortages",
    "lock_fifo_entries",
    "restore_sale_stock",
    "validate_stock_availability",
]
