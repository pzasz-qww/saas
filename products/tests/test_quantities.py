from dataclasses import FrozenInstanceError
from decimal import Decimal

from django.test import SimpleTestCase

from products.quantities import (
    NormalizedQuantity,
    QUANTITY_UNIT_CHOICES,
    QuantityConversionError,
    normalize_quantity,
)


class QuantityNormalizationTests(SimpleTestCase):
    def assert_normalized(self, value, unit, *, quantity, dimension, base_unit):
        result = normalize_quantity(value, unit)

        self.assertIsInstance(result, NormalizedQuantity)
        self.assertIsInstance(result.quantity, Decimal)
        self.assertEqual(result.quantity, Decimal(quantity))
        self.assertEqual(result.dimension, dimension)
        self.assertEqual(result.base_unit, base_unit)

    def test_milligrams_are_normalized_to_grams(self):
        self.assert_normalized(
            Decimal("750"),
            "mg",
            quantity="0.750",
            dimension="weight",
            base_unit="g",
        )

    def test_grams_remain_grams(self):
        self.assert_normalized(
            Decimal("0.001"),
            "g",
            quantity="0.001",
            dimension="weight",
            base_unit="g",
        )

    def test_kilograms_are_normalized_to_grams(self):
        self.assert_normalized(
            Decimal("30"),
            "kg",
            quantity="30000",
            dimension="weight",
            base_unit="g",
        )

    def test_milliliters_remain_milliliters(self):
        self.assert_normalized(
            Decimal("50"),
            "mL",
            quantity="50",
            dimension="volume",
            base_unit="mL",
        )

    def test_liters_are_normalized_to_milliliters(self):
        self.assert_normalized(
            Decimal("2.5"),
            "L",
            quantity="2500.0",
            dimension="volume",
            base_unit="mL",
        )

    def test_units_remain_units(self):
        self.assert_normalized(
            Decimal("3"),
            "unit",
            quantity="3",
            dimension="count",
            base_unit="unit",
        )

    def test_decimal_text_and_integer_inputs_remain_exact(self):
        decimal_text = normalize_quantity("0.123456", "g")
        integer = normalize_quantity(2, "kg")

        self.assertEqual(decimal_text.quantity, Decimal("0.123456"))
        self.assertEqual(integer.quantity, Decimal("2000"))

    def test_decimal_comma_is_accepted_without_float_conversion(self):
        result = normalize_quantity("2,5", "L")

        self.assertEqual(result.quantity, Decimal("2500.0"))

    def test_friendly_unit_aliases_are_canonicalized(self):
        cases = (
            ("unidade", "unit", "count"),
            ("gramas", "g", "weight"),
            ("quilograma", "g", "weight"),
            ("ml", "mL", "volume"),
            ("litros", "mL", "volume"),
        )

        for alias, base_unit, dimension in cases:
            with self.subTest(alias=alias):
                result = normalize_quantity(Decimal("1"), alias)
                self.assertEqual(result.base_unit, base_unit)
                self.assertEqual(result.dimension, dimension)

    def test_every_public_choice_is_supported(self):
        self.assertEqual(
            [value for value, _label in QUANTITY_UNIT_CHOICES],
            ["unit", "mg", "g", "kg", "mL", "L"],
        )

        for unit, _label in QUANTITY_UNIT_CHOICES:
            with self.subTest(unit=unit):
                self.assertIsInstance(
                    normalize_quantity(Decimal("1"), unit),
                    NormalizedQuantity,
                )

    def test_result_is_immutable(self):
        result = normalize_quantity(Decimal("1"), "g")

        with self.assertRaises(FrozenInstanceError):
            result.quantity = Decimal("2")

    def test_bool_and_float_values_are_rejected(self):
        for value in (True, False, 0.1, 1.0):
            with self.subTest(value=value):
                with self.assertRaises(QuantityConversionError):
                    normalize_quantity(value, "g")

    def test_non_finite_values_are_rejected(self):
        for value in (
            Decimal("NaN"),
            Decimal("Infinity"),
            Decimal("-Infinity"),
            "NaN",
            "Infinity",
            "-Infinity",
        ):
            with self.subTest(value=value):
                with self.assertRaises(QuantityConversionError):
                    normalize_quantity(value, "g")

    def test_zero_and_negative_values_are_rejected(self):
        for value in (Decimal("0"), Decimal("-0"), Decimal("-0.001"), "-2"):
            with self.subTest(value=value):
                with self.assertRaises(QuantityConversionError):
                    normalize_quantity(value, "g")

    def test_invalid_quantity_inputs_are_rejected(self):
        for value in (None, "", "   ", "abc", "1.2.3", "1,2.3", object()):
            with self.subTest(value=value):
                with self.assertRaises(QuantityConversionError):
                    normalize_quantity(value, "g")

    def test_invalid_units_are_rejected(self):
        for unit in (None, "", "   ", "oz", "lb", 1):
            with self.subTest(unit=unit):
                with self.assertRaises(QuantityConversionError):
                    normalize_quantity(Decimal("1"), unit)
