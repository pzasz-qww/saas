"""Conversão exata entre quantidade vendida e consumo físico de estoque."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from .quantities import base_unit_for_dimension


ZERO = Decimal("0")
ONE = Decimal("1")


class PhysicalSaleQuantityError(ValueError):
    """Raised when a product cannot be converted to physical stock safely."""


@dataclass(frozen=True, slots=True)
class PhysicalConsumption:
    sale_quantity: Decimal
    sale_form: str
    quantity_per_sale_unit: Decimal
    total_quantity: Decimal
    base_unit: str


@dataclass(frozen=True, slots=True)
class SaleAvailability:
    physical_stock: Decimal
    quantity_per_sale_unit: Decimal
    available_sale_quantity: Decimal
    physical_remainder: Decimal
    base_unit: str


def _decimal(value, *, label, positive):
    if isinstance(value, bool) or isinstance(value, float):
        raise PhysicalSaleQuantityError(
            f"{label} deve ser informado sem usar float."
        )

    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise PhysicalSaleQuantityError(f"{label} inválido.") from None

    if not parsed.is_finite():
        raise PhysicalSaleQuantityError(f"{label} deve ser finito.")
    if positive and parsed <= ZERO:
        raise PhysicalSaleQuantityError(f"{label} deve ser positivo.")
    if not positive and parsed < ZERO:
        raise PhysicalSaleQuantityError(f"{label} não pode ser negativo.")
    return parsed


def physical_quantity_per_sale_unit(product):
    """Return the physical stock consumed by one commercial sale quantity."""
    sale_form = product.sale_form

    if sale_form == "unit":
        base_unit = base_unit_for_dimension(product.stock_dimension)
        if base_unit is None:
            raise PhysicalSaleQuantityError(
                "A dimensão de estoque do produto é inválida."
            )
        return ONE, base_unit

    if sale_form == "dose":
        if product.stock_dimension != "volume":
            raise PhysicalSaleQuantityError(
                "Produtos vendidos por dose precisam controlar estoque por volume."
            )
        return (
            _decimal(product.dose_ml, label="O volume da dose", positive=True),
            "mL",
        )

    if sale_form == "portion":
        if product.stock_dimension != "weight":
            raise PhysicalSaleQuantityError(
                "Produtos vendidos por porção precisam controlar estoque por peso."
            )
        return (
            _decimal(product.portion_g, label="O peso da porção", positive=True),
            "g",
        )

    raise PhysicalSaleQuantityError("A forma de venda do produto é inválida.")


def get_physical_consumption(product, sale_quantity):
    """Convert a positive commercial quantity to the physical base unit."""
    commercial_quantity = _decimal(
        sale_quantity,
        label="A quantidade vendida",
        positive=True,
    )
    quantity_per_sale_unit, base_unit = physical_quantity_per_sale_unit(product)
    return PhysicalConsumption(
        sale_quantity=commercial_quantity,
        sale_form=product.sale_form,
        quantity_per_sale_unit=quantity_per_sale_unit,
        total_quantity=commercial_quantity * quantity_per_sale_unit,
        base_unit=base_unit,
    )


def get_sale_availability(product, physical_stock=None):
    """Calculate complete sale quantities and the physical remainder on demand."""
    if physical_stock is None:
        physical_stock = product.current_stock
    stock = _decimal(
        physical_stock,
        label="O estoque físico",
        positive=False,
    )
    quantity_per_sale_unit, base_unit = physical_quantity_per_sale_unit(product)
    available = stock // quantity_per_sale_unit
    remainder = stock - (available * quantity_per_sale_unit)
    return SaleAvailability(
        physical_stock=stock,
        quantity_per_sale_unit=quantity_per_sale_unit,
        available_sale_quantity=available,
        physical_remainder=remainder,
        base_unit=base_unit,
    )


__all__ = [
    "PhysicalConsumption",
    "PhysicalSaleQuantityError",
    "SaleAvailability",
    "get_physical_consumption",
    "get_sale_availability",
    "physical_quantity_per_sale_unit",
]
