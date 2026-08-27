from decimal import Decimal

from django.test import SimpleTestCase

from products.money import InvalidMoneyValue, decimal_amount, round_money


class MoneyPolicyTests(SimpleTestCase):
    def test_intermediate_cost_is_not_rounded(self):
        unit_cost = decimal_amount("25") / Decimal("1000000")

        self.assertEqual(unit_cost, Decimal("0.000025"))

    def test_final_money_uses_central_rounding_policy(self):
        self.assertEqual(round_money("1.005"), Decimal("1.01"))

    def test_non_finite_money_is_rejected(self):
        for value in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(value=value):
                with self.assertRaises(InvalidMoneyValue):
                    decimal_amount(value)

    def test_float_money_is_rejected(self):
        with self.assertRaises(InvalidMoneyValue):
            decimal_amount(0.1)
