from django.test import SimpleTestCase

from products.category_names import clean_category_name, normalize_category_name


class CategoryNameNormalizationTests(SimpleTestCase):
    def test_visible_name_only_collapses_unnecessary_whitespace(self):
        self.assertEqual(
            clean_category_name("  Bebidas   sem álcool  "),
            "Bebidas sem álcool",
        )

    def test_empty_values_are_cleaned_to_an_empty_name(self):
        for value in (None, "", "   ", "\t\n"):
            with self.subTest(value=value):
                self.assertEqual(clean_category_name(value), "")
                self.assertEqual(normalize_category_name(value), "")

    def test_normalization_ignores_case_and_repeated_whitespace(self):
        variants = (
            "Cervejas",
            "cervejas",
            " Cervejas ",
            "CERVEJAS",
            "  CerVEJas  ",
        )

        self.assertEqual(
            {normalize_category_name(value) for value in variants},
            {"cervejas"},
        )

    def test_normalization_is_accent_insensitive_and_deterministic(self):
        self.assertEqual(normalize_category_name("Porções"), "porcoes")
        self.assertEqual(
            normalize_category_name("Porções"),
            normalize_category_name("Porcoes"),
        )

    def test_cleaning_preserves_case_and_accents_for_display(self):
        self.assertEqual(clean_category_name("  Porções  "), "Porções")

