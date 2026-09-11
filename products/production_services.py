"""Atomic production of pre-portioned products using the shared FIFO stock."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import (
    Product,
    Production,
    ProductionConsumption,
    StockEntry,
    StockMovement,
)
from .recipe_services import (
    InvalidOperationalRecipe,
    expand_product_components,
)
from .sale_quantities import PhysicalSaleQuantityError, get_physical_consumption
from .services import (
    InvalidStockOperation,
    StockConcurrencyError,
    StockServiceError,
    _company_id,
    _lock_company_products,
    _nonnegative_decimal,
    calculate_fifo_cost,
    consume_production_stock,
    lock_fifo_entries,
)


ZERO = Decimal("0")
PHYSICAL_QUANTUM = Decimal("0.000001")


class ProductionServiceError(StockServiceError):
    """Base error for production operations that must be rolled back."""


class InvalidProduction(ProductionServiceError):
    """Raised when production input or history is inconsistent."""


class ProductionReversalError(ProductionServiceError):
    """Raised when a production can no longer be safely reversed."""


@dataclass(frozen=True, slots=True)
class ProductionResult:
    production: Production
    output_entry: StockEntry


@dataclass(frozen=True, slots=True)
class ProductionReversalResult:
    production: Production
    reversed: bool


def _physical_decimal(value, *, label, positive):
    if isinstance(value, (bool, float)):
        raise InvalidProduction(f"{label} inválido.")
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
        quantized = parsed.quantize(PHYSICAL_QUANTUM)
    except (InvalidOperation, TypeError, ValueError):
        raise InvalidProduction(f"{label} inválido.") from None
    if not parsed.is_finite() or quantized != parsed:
        raise InvalidProduction(
            f"{label} deve usar no máximo seis casas decimais."
        )
    if positive and parsed <= ZERO:
        raise InvalidProduction(f"{label} deve ser positivo.")
    if not positive and parsed < ZERO:
        raise InvalidProduction(f"{label} não pode ser negativo.")
    return quantized


def _production_date(value, *, label, required):
    if value in (None, ""):
        if required:
            raise InvalidProduction(f"Informe {label}.")
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise InvalidProduction(f"Informe {label} válida.")


def _normalize_component_values(expanded_components, component_values):
    expected_ids = {
        component.source_component.pk for component in expanded_components
    }
    if component_values is None:
        raw_values = {
            component.source_component.pk: {
                "actual_quantity": component.total_quantity,
                "loss_quantity": ZERO,
            }
            for component in expanded_components
        }
    else:
        raw_values = {}
        for raw_id, values in component_values.items():
            try:
                component_id = int(raw_id)
            except (TypeError, ValueError):
                raise InvalidProduction("Componente informado é inválido.") from None
            if component_id in raw_values or not isinstance(values, dict):
                raise InvalidProduction("Os consumos informados são inválidos.")
            raw_values[component_id] = values

    if set(raw_values) != expected_ids:
        raise InvalidProduction(
            "Informe o consumo real de todos os componentes da produção."
        )

    normalized = {}
    for component in expanded_components:
        values = raw_values[component.source_component.pk]
        actual = _physical_decimal(
            values.get("actual_quantity"),
            label=f"O consumo real de {component.ingredient.name}",
            positive=True,
        )
        loss = _physical_decimal(
            values.get("loss_quantity", ZERO),
            label=f"A perda de {component.ingredient.name}",
            positive=False,
        )
        if loss > actual:
            raise InvalidProduction(
                f"A perda de {component.ingredient.name} não pode superar o consumo real."
            )
        normalized[component.source_component.pk] = (actual, loss)
    return normalized


@transaction.atomic
def create_production(
    *,
    company,
    product,
    planned_quantity,
    produced_quantity,
    production_date=None,
    expiration_date=None,
    component_values=None,
    notes=None,
    created_by=None,
):
    """Consume ingredients and create one traceable output lot atomically."""
    company_id = _company_id(company)
    product_id = getattr(product, "pk", product)
    if product_id is None:
        raise InvalidProduction("O produto precisa estar salvo.")
    locked_products = _lock_company_products(
        company_id=company_id,
        product_ids=[product_id],
    )
    product = locked_products[product_id]
    if not product.active or not (
        product.inventory_role == "prepared"
        and product.preparation_mode == "pre_portioned"
    ):
        raise InvalidProduction(
            "Somente produto ativo e preparado antecipadamente pode ser produzido."
        )

    planned = _physical_decimal(
        planned_quantity,
        label="A quantidade planejada",
        positive=True,
    )
    produced = _physical_decimal(
        produced_quantity,
        label="A quantidade produzida",
        positive=True,
    )
    operational_date = _production_date(
        timezone.localdate() if production_date is None else production_date,
        label="uma data de produção",
        required=True,
    )
    expiration = _production_date(
        expiration_date,
        label="uma validade",
        required=False,
    )
    if expiration is not None and expiration < operational_date:
        raise InvalidProduction(
            "A validade não pode ser anterior à data da produção."
        )

    try:
        expanded_components = expand_product_components(
            product,
            planned,
            lock=True,
        )
        output_consumption = get_physical_consumption(product, produced)
    except (InvalidOperationalRecipe, PhysicalSaleQuantityError) as error:
        raise InvalidProduction(str(error)) from error

    normalized_values = _normalize_component_values(
        expanded_components,
        component_values,
    )
    actual_by_product = {}
    for component in expanded_components:
        actual, _loss = normalized_values[component.source_component.pk]
        if component.ingredient.pk in actual_by_product:
            raise InvalidProduction("A receita possui ingredientes duplicados.")
        actual_by_product[component.ingredient.pk] = actual

    entries_by_product = lock_fifo_entries(
        company=company_id,
        product_quantities=actual_by_product,
    )
    cost_by_component = {}
    total_cost = ZERO
    for component in expanded_components:
        actual, _loss = normalized_values[component.source_component.pk]
        component_cost = calculate_fifo_cost(
            product_id=component.ingredient.pk,
            quantity=actual,
            entries=entries_by_product[component.ingredient.pk],
        )
        cost_by_component[component.source_component.pk] = component_cost
        total_cost += component_cost

    production = Production.objects.create(
        company_id=company_id,
        product=product,
        planned_quantity=planned,
        produced_quantity=produced,
        production_date=operational_date,
        expiration_date=expiration,
        total_cost=total_cost,
        notes=(notes or "").strip() or None,
        created_by=created_by,
    )

    for component in expanded_components:
        actual, loss = normalized_values[component.source_component.pk]
        consumption = ProductionConsumption.objects.create(
            company_id=company_id,
            production=production,
            source_component=component.source_component,
            ingredient=component.ingredient,
            quantity_per_planned_unit=component.quantity_per_sale_unit,
            theoretical_quantity=component.total_quantity,
            actual_quantity=actual,
            loss_quantity=loss,
            base_unit=component.base_unit,
            total_cost=cost_by_component[component.source_component.pk],
        )
        consume_production_stock(
            company=company_id,
            production_consumption=consumption,
            entries_by_product=entries_by_product,
            created_by=created_by,
        )

    output_quantity = _physical_decimal(
        output_consumption.total_quantity,
        label="A quantidade física produzida",
        positive=True,
    )
    output_entry = StockEntry.objects.create(
        company_id=company_id,
        product=product,
        production=production,
        input_quantity=output_quantity,
        input_unit=output_consumption.base_unit,
        quantity_added=output_quantity,
        base_unit=output_consumption.base_unit,
        remaining_quantity=output_quantity,
        total_cost=total_cost,
        entry_date=operational_date,
        expiration_date=expiration,
        notes=f"Lote gerado pela produção #{production.pk}.",
        created_by=created_by,
    )
    StockMovement.objects.create(
        company_id=company_id,
        product=product,
        stock_entry=output_entry,
        production=production,
        movement_type="production_output",
        quantity=output_quantity,
        sale_value=ZERO,
        cost_value=total_cost,
        reason=f"Produção #{production.pk}: entrada do produto preparado",
        notes=None,
        created_by=created_by,
    )
    return ProductionResult(
        production=production,
        output_entry=output_entry,
    )


@transaction.atomic
def reverse_production(*, company, production_id, user=None):
    """Reverse an untouched production and return inputs to original FIFO lots."""
    company_id = _company_id(company)
    try:
        production = (
            Production.objects.select_for_update()
            .select_related("product")
            .get(pk=production_id, company_id=company_id)
        )
    except Production.DoesNotExist:
        raise InvalidProduction("Produção inexistente para esta empresa.") from None

    if production.status == Production.STATUS_REVERSED:
        return ProductionReversalResult(production=production, reversed=False)
    if production.status != Production.STATUS_COMPLETED:
        raise ProductionReversalError("O estado da produção não permite reversão.")

    consumptions = list(
        ProductionConsumption.objects.select_for_update()
        .filter(production=production, company_id=company_id)
        .select_related("ingredient")
        .order_by("ingredient_id", "id")
    )
    if not consumptions:
        raise ProductionReversalError(
            "A produção não possui consumos rastreáveis."
        )
    _lock_company_products(
        company_id=company_id,
        product_ids=[
            production.product_id,
            *(consumption.ingredient_id for consumption in consumptions),
        ],
    )

    try:
        output_entry = StockEntry.objects.select_for_update().get(
            production=production,
            company_id=company_id,
            product_id=production.product_id,
        )
    except StockEntry.DoesNotExist:
        raise ProductionReversalError(
            "O lote produzido não existe ou perdeu sua rastreabilidade."
        ) from None

    expected_output = output_entry.quantity_added
    if (
        expected_output <= ZERO
        or output_entry.remaining_quantity != expected_output
    ):
        raise ProductionReversalError(
            "A produção não pode ser revertida porque o lote produzido não está intacto."
        )

    production_movements = list(
        StockMovement.objects.select_for_update()
        .filter(production=production)
        .select_related("stock_entry")
        .order_by("product_id", "stock_entry_id", "id")
    )
    output_movements = [
        movement
        for movement in production_movements
        if movement.movement_type == "production_output"
    ]
    input_movements = [
        movement
        for movement in production_movements
        if movement.movement_type == "production_consumption"
    ]
    if len(output_movements) != 1:
        raise ProductionReversalError("A entrada da produção é inconsistente.")
    output_movement = output_movements[0]
    if (
        output_movement.stock_entry_id != output_entry.pk
        or output_movement.product_id != production.product_id
        or output_movement.quantity != expected_output
        or output_movement.production_consumption_id is not None
    ):
        raise ProductionReversalError("A entrada da produção é inconsistente.")

    other_output_movements = output_entry.movements.exclude(
        pk=output_movement.pk
    )
    if other_output_movements.exists():
        raise ProductionReversalError(
            "A produção não pode ser revertida porque seu lote já possui movimentações."
        )

    consumption_by_id = {consumption.pk: consumption for consumption in consumptions}
    totals_by_consumption = {consumption.pk: ZERO for consumption in consumptions}
    for movement in input_movements:
        consumption = consumption_by_id.get(movement.production_consumption_id)
        if (
            consumption is None
            or movement.company_id != company_id
            or movement.product_id != consumption.ingredient_id
            or movement.stock_entry_id is None
            or movement.quantity <= ZERO
        ):
            raise ProductionReversalError(
                "A produção possui consumo de ingrediente inconsistente."
            )
        totals_by_consumption[consumption.pk] += movement.quantity
    if any(
        totals_by_consumption[consumption.pk] != consumption.actual_quantity
        for consumption in consumptions
    ):
        raise ProductionReversalError(
            "A produção possui consumo incompleto de ingredientes."
        )
    if len(input_movements) + 1 != len(production_movements):
        raise ProductionReversalError(
            "A produção já possui reversões ou movimentos inesperados."
        )

    original_entry_ids = {movement.stock_entry_id for movement in input_movements}
    original_entries = list(
        StockEntry.objects.select_for_update()
        .filter(pk__in=original_entry_ids)
        .order_by("product_id", "created_at", "id")
    )
    entry_by_id = {entry.pk: entry for entry in original_entries}
    if set(entry_by_id) != original_entry_ids:
        raise ProductionReversalError(
            "Um lote de ingrediente utilizado não existe mais."
        )

    updated_output = StockEntry.objects.filter(
        pk=output_entry.pk,
        remaining_quantity=expected_output,
    ).update(remaining_quantity=ZERO)
    if updated_output != 1:
        raise StockConcurrencyError(
            "O saldo do lote produzido mudou durante a reversão."
        )
    StockMovement.objects.create(
        company_id=company_id,
        product_id=production.product_id,
        stock_entry=output_entry,
        production=production,
        reversal_of=output_movement,
        movement_type="production_output_reversal",
        quantity=expected_output,
        sale_value=ZERO,
        cost_value=production.total_cost,
        reason=f"Reversão da produção #{production.pk}",
        notes="Retirada integral do lote produzido.",
        created_by=user,
    )

    for original in input_movements:
        entry = entry_by_id[original.stock_entry_id]
        if (
            entry.company_id != company_id
            or entry.product_id != original.product_id
        ):
            raise ProductionReversalError(
                "Um lote original pertence a outra empresa ou produto."
            )
        current = _nonnegative_decimal(
            entry.remaining_quantity,
            field_name=f"saldo da entrada #{entry.pk}",
        )
        if current + original.quantity > entry.quantity_added:
            raise ProductionReversalError(
                f"O lote #{entry.pk} não comporta a devolução rastreada."
            )
        updated = StockEntry.objects.filter(
            pk=entry.pk,
            company_id=company_id,
            product_id=original.product_id,
            remaining_quantity__lte=F("quantity_added") - original.quantity,
        ).update(remaining_quantity=F("remaining_quantity") + original.quantity)
        if updated != 1:
            raise StockConcurrencyError(
                f"O saldo do lote #{entry.pk} mudou durante a reversão."
            )
        entry.remaining_quantity += original.quantity
        StockMovement.objects.create(
            company_id=company_id,
            product_id=original.product_id,
            stock_entry=entry,
            production=production,
            production_consumption_id=original.production_consumption_id,
            reversal_of=original,
            movement_type="production_return",
            quantity=original.quantity,
            sale_value=ZERO,
            cost_value=original.cost_value,
            reason=f"Reversão da produção #{production.pk}",
            notes=f"Retorno do consumo #{original.production_consumption_id}.",
            created_by=user,
        )

    production.status = Production.STATUS_REVERSED
    production.reversed_by = user
    production.reversed_at = timezone.now()
    production.save(update_fields=("status", "reversed_by", "reversed_at"))
    return ProductionReversalResult(production=production, reversed=True)


__all__ = [
    "InvalidProduction",
    "ProductionResult",
    "ProductionReversalError",
    "ProductionReversalResult",
    "ProductionServiceError",
    "create_production",
    "reverse_production",
]
