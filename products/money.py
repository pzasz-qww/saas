from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


MONEY_QUANTUM = Decimal("0.01")


class InvalidMoneyValue(ValueError):
    """Raised when a value cannot participate in monetary calculations."""


def decimal_amount(value):
    """Return a finite Decimal without applying monetary rounding."""
    if isinstance(value, (bool, float)):
        raise InvalidMoneyValue("Valor monetário inválido.")

    try:
        amount = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise InvalidMoneyValue("Valor monetário inválido.") from None

    if not amount.is_finite():
        raise InvalidMoneyValue("Valor monetário deve ser finito.")

    return amount


def round_money(value):
    """Round only a final monetary amount, using the project's single policy."""
    return decimal_amount(value).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


__all__ = [
    "InvalidMoneyValue",
    "MONEY_QUANTUM",
    "decimal_amount",
    "round_money",
]
