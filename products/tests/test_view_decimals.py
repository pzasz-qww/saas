from decimal import Decimal

from django.test import SimpleTestCase

from products.views import parse_decimal


class ViewDecimalParsingTests(SimpleTestCase):
    def test_decimal_comma_is_accepted(self):
        self.assertEqual(parse_decimal("0,001"), Decimal("0.001"))

    def test_non_finite_values_are_rejected(self):
        for value in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(value=value):
                self.assertIsNone(parse_decimal(value))
