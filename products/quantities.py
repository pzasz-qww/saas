"""Conversões exatas entre unidades físicas usadas pelo estoque.

Este módulo é a fonte única dos fatores de conversão. Ele não arredonda nem
quantiza resultados: qualquer decisão sobre a precisão de persistência ou de
exibição pertence à fronteira que consumir o valor normalizado.
"""

from dataclasses import dataclass
from decimal import Decimal, DecimalException, InvalidOperation


class QuantityConversionError(ValueError):
    """Raised when a quantity cannot be safely normalized."""


@dataclass(frozen=True, slots=True)
class NormalizedQuantity:
    """A positive quantity expressed in its dimension's base unit."""

    quantity: Decimal
    dimension: str
    base_unit: str


QUANTITY_UNIT_CHOICES = (
    ("unit", "unidade"),
    ("mg", "mg"),
    ("g", "g"),
    ("kg", "kg"),
    ("mL", "mL"),
    ("L", "L"),
)


@dataclass(frozen=True, slots=True)
class _UnitDefinition:
    dimension: str
    base_unit: str
    factor: Decimal


_UNIT_DEFINITIONS = {
    "unit": _UnitDefinition("count", "unit", Decimal("1")),
    "mg": _UnitDefinition("weight", "g", Decimal("0.001")),
    "g": _UnitDefinition("weight", "g", Decimal("1")),
    "kg": _UnitDefinition("weight", "g", Decimal("1000")),
    "mL": _UnitDefinition("volume", "mL", Decimal("1")),
    "L": _UnitDefinition("volume", "mL", Decimal("1000")),
}

UNITS_BY_DIMENSION = {
    "count": ("unit",),
    "weight": ("mg", "g", "kg"),
    "volume": ("mL", "L"),
}

BASE_UNIT_BY_DIMENSION = {
    dimension: _UNIT_DEFINITIONS[units[0]].base_unit
    for dimension, units in UNITS_BY_DIMENSION.items()
}

_UNIT_ALIASES = {
    "un": "unit",
    "unid": "unit",
    "unidade": "unit",
    "unidades": "unit",
    "miligrama": "mg",
    "miligramas": "mg",
    "grama": "g",
    "gramas": "g",
    "quilo": "kg",
    "quilos": "kg",
    "quilograma": "kg",
    "quilogramas": "kg",
    "ml": "mL",
    "mililitro": "mL",
    "mililitros": "mL",
    "l": "L",
    "litro": "L",
    "litros": "L",
}


def _parse_decimal(value):
    if isinstance(value, bool) or isinstance(value, float):
        raise QuantityConversionError(
            "A quantidade deve ser informada sem usar float."
        )

    if isinstance(value, Decimal):
        parsed = value
    elif isinstance(value, int):
        parsed = Decimal(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise QuantityConversionError("Informe uma quantidade válida.")

        if "," in text:
            if "." in text or text.count(",") != 1:
                raise QuantityConversionError("Informe uma quantidade válida.")
            text = text.replace(",", ".")

        try:
            parsed = Decimal(text)
        except InvalidOperation:
            raise QuantityConversionError(
                "Informe uma quantidade válida."
            ) from None
    else:
        raise QuantityConversionError("Informe uma quantidade válida.")

    if not parsed.is_finite():
        raise QuantityConversionError("A quantidade deve ser finita.")

    if parsed <= 0:
        raise QuantityConversionError("A quantidade deve ser positiva.")

    return parsed


def _canonical_unit(unit):
    if not isinstance(unit, str):
        raise QuantityConversionError("Informe uma unidade válida.")

    value = unit.strip()
    if not value:
        raise QuantityConversionError("Informe uma unidade válida.")

    if value in _UNIT_DEFINITIONS:
        return value

    canonical = _UNIT_ALIASES.get(value.casefold())
    if canonical is None:
        raise QuantityConversionError(f"Unidade não suportada: {value}.")

    return canonical


def normalize_quantity(quantity, unit):
    """Normalize a positive physical quantity without rounding.

    ``quantity`` accepts ``Decimal``, exact integers, and decimal text (with a
    dot or a comma). Binary floating-point values are deliberately rejected.
    ``unit`` accepts every canonical value from ``QUANTITY_UNIT_CHOICES`` plus
    friendly Portuguese aliases such as ``unidade``, ``litro`` and ``grama``.
    """

    parsed_quantity = _parse_decimal(quantity)
    canonical_unit = _canonical_unit(unit)
    definition = _UNIT_DEFINITIONS[canonical_unit]

    try:
        normalized_quantity = parsed_quantity * definition.factor
    except DecimalException:
        raise QuantityConversionError(
            "A quantidade não pôde ser normalizada."
        ) from None

    if not normalized_quantity.is_finite():
        raise QuantityConversionError(
            "A quantidade normalizada deve ser finita."
        )

    return NormalizedQuantity(
        quantity=normalized_quantity,
        dimension=definition.dimension,
        base_unit=definition.base_unit,
    )


def units_for_dimension(dimension):
    """Return the canonical input units accepted by one stock dimension."""
    return UNITS_BY_DIMENSION.get(dimension, ())


def base_unit_for_dimension(dimension):
    """Return the canonical storage unit for one stock dimension."""
    return BASE_UNIT_BY_DIMENSION.get(dimension)


__all__ = [
    "BASE_UNIT_BY_DIMENSION",
    "NormalizedQuantity",
    "QUANTITY_UNIT_CHOICES",
    "QuantityConversionError",
    "UNITS_BY_DIMENSION",
    "base_unit_for_dimension",
    "normalize_quantity",
    "units_for_dimension",
]
