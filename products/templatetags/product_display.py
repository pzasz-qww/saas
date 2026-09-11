from django import template

from products.presentation import (
    InvalidPresentationValue,
    format_decimal,
    format_money,
    format_quantity,
)


register = template.Library()


@register.filter
def decimal_ptbr(value):
    try:
        return format_decimal(value)
    except InvalidPresentationValue:
        return "—"


@register.filter
def physical_quantity(value, base_unit):
    try:
        return format_quantity(value, base_unit)
    except InvalidPresentationValue:
        return "—"


@register.filter
def brl(value):
    try:
        return format_money(value)
    except InvalidPresentationValue:
        return "—"

