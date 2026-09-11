"""Formatting helpers for operator-facing quantities and money."""

from decimal import Decimal, InvalidOperation

from .money import InvalidMoneyValue, round_money


class InvalidPresentationValue(ValueError):
    """Raised when a value cannot be safely formatted for presentation."""


UNIT_LABELS = {
    "unit": "un",
    "g": "g",
    "kg": "kg",
    "mL": "mL",
    "L": "L",
}


def _presentation_decimal(value):
    if isinstance(value, (bool, float)):
        raise InvalidPresentationValue("A quantidade deve ser informada como Decimal.")
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise InvalidPresentationValue("Quantidade inválida para apresentação.") from None
    if not parsed.is_finite():
        raise InvalidPresentationValue("A quantidade deve ser finita.")
    return parsed


def format_decimal(value, *, decimal_separator=","):
    """Render a finite decimal without insignificant trailing zeroes."""
    parsed = _presentation_decimal(value)
    if parsed == 0:
        parsed = Decimal("0")
    formatted = format(parsed, "f")
    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")
    if decimal_separator != ".":
        formatted = formatted.replace(".", decimal_separator)
    return formatted


def format_decimal_input(value):
    """Render a compact decimal suitable for an HTML number input."""
    return format_decimal(value, decimal_separator=".")


def format_quantity(value, base_unit):
    """Render a physical quantity, promoting g/kg and mL/L from 1000."""
    quantity = _presentation_decimal(value)
    display_unit = base_unit
    if base_unit == "g" and abs(quantity) >= Decimal("1000"):
        quantity /= Decimal("1000")
        display_unit = "kg"
    elif base_unit == "mL" and abs(quantity) >= Decimal("1000"):
        quantity /= Decimal("1000")
        display_unit = "L"

    unit_label = UNIT_LABELS.get(display_unit, str(display_unit or "").strip())
    value_text = format_decimal(quantity)
    return f"{value_text} {unit_label}".strip()


def format_money(value):
    """Render money using the project's rounding policy and pt-BR punctuation."""
    try:
        amount = round_money(value)
    except InvalidMoneyValue as error:
        raise InvalidPresentationValue(str(error)) from error
    sign = "-" if amount < 0 else ""
    integer, fraction = f"{abs(amount):.2f}".split(".")
    grouped_integer = f"{int(integer):,}".replace(",", ".")
    return f"R$ {sign}{grouped_integer},{fraction}"


def friendly_recipe_error(error):
    """Translate domain-safe recipe errors into concise operator language."""
    message = str(error)
    if "não possui componentes" in message:
        return (
            "Cadastre ao menos um ingrediente antes de vender ou produzir "
            "este produto."
        )
    return message


__all__ = [
    "InvalidPresentationValue",
    "format_decimal",
    "format_decimal_input",
    "format_money",
    "format_quantity",
    "friendly_recipe_error",
]
