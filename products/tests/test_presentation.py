from decimal import Decimal
from unittest.mock import patch

from django.template import Context, Template
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from products import views as product_views
from products.presentation import (
    InvalidPresentationValue,
    format_decimal,
    format_money,
    format_percentage,
    format_quantity,
)

from .helpers import make_company, make_entry, make_product, make_user


class QuantityPresentationTests(SimpleTestCase):
    def test_weight_formatting(self):
        cases = (
            ("0.5", "0,5 g"),
            ("500", "500 g"),
            ("1000", "1 kg"),
            ("1250", "1,25 kg"),
            ("5000", "5 kg"),
            ("30000", "30 kg"),
        )
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(format_quantity(Decimal(raw), "g"), expected)

    def test_volume_formatting(self):
        cases = (
            ("0.5", "0,5 mL"),
            ("500", "500 mL"),
            ("1000", "1 L"),
            ("1250", "1,25 L"),
            ("4500", "4,5 L"),
        )
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(format_quantity(Decimal(raw), "mL"), expected)

    def test_count_formatting(self):
        self.assertEqual(format_quantity(Decimal("1"), "unit"), "1 un")
        self.assertEqual(format_quantity(Decimal("8"), "unit"), "8 un")

    def test_trailing_zeroes_and_decimal_comma(self):
        self.assertEqual(format_decimal(Decimal("5.000000")), "5")
        self.assertEqual(format_decimal(Decimal("5.500000")), "5,5")
        self.assertEqual(format_decimal(Decimal("5.250000")), "5,25")

    def test_negative_difference_uses_the_same_physical_rule(self):
        self.assertEqual(format_quantity(Decimal("-200"), "g"), "-200 g")
        self.assertEqual(format_quantity(Decimal("-1250"), "g"), "-1,25 kg")

    def test_formatting_does_not_change_original_decimal(self):
        original = Decimal("5000.000000")

        rendered = format_quantity(original, "g")

        self.assertEqual(rendered, "5 kg")
        self.assertEqual(original, Decimal("5000.000000"))
        self.assertEqual(original.as_tuple().exponent, -6)

    def test_float_is_rejected(self):
        with self.assertRaises(InvalidPresentationValue):
            format_quantity(5000.0, "g")

    def test_money_uses_brazilian_presentation(self):
        self.assertEqual(format_money(Decimal("16.250000")), "R$ 16,25")
        self.assertEqual(format_money(Decimal("130")), "R$ 130,00")
        self.assertEqual(format_money(Decimal("299250")), "R$ 299.250,00")

    def test_percentage_uses_one_decimal_only_when_needed(self):
        cases = (
            ("100", "100%"),
            ("80.000000", "80%"),
            ("87.5", "87,5%"),
            ("88.88888888888888888888888889", "88,9%"),
            ("71.42857142857142857142857143", "71,4%"),
        )
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(format_percentage(Decimal(raw)), expected)

    def test_template_filters_reuse_the_central_formatter(self):
        template = Template(
            "{% load product_display %}"
            "{{ weight|physical_quantity:'g' }}|"
            "{{ volume|physical_quantity:'mL' }}|"
            "{{ money|brl }}|"
            "{{ percentage|percentage_ptbr }}"
        )

        rendered = template.render(
            Context(
                {
                    "weight": Decimal("5000.000000"),
                    "volume": Decimal("4500.000000"),
                    "money": Decimal("16.250000"),
                    "percentage": Decimal("88.88888888888888888888888889"),
                }
            )
        )

        self.assertEqual(rendered, "5 kg|4,5 L|R$ 16,25|88,9%")


class PdfPresentationTests(TestCase):
    def test_stock_pdf_reuses_quantity_and_money_formatters(self):
        company = make_company(name="Bar do PDF")
        user = make_user(company=company, role="owner")
        product = make_product(
            company=company,
            name="Carne",
            sale_price=Decimal("16.25"),
            stock_dimension="weight",
        )
        make_entry(product=product, quantity="5000")
        self.client.force_login(user)
        captured_tables = []
        real_table = product_views.Table

        def capture_table(data, *args, **kwargs):
            captured_tables.append(data)
            return real_table(data, *args, **kwargs)

        with patch("products.views.Table", side_effect=capture_table):
            response = self.client.get(reverse("products:stock_report_pdf"))

        self.assertEqual(response.status_code, 200)
        flattened_cells = [
            str(cell)
            for table_data in captured_tables
            for row in table_data
            for cell in row
        ]
        self.assertIn("5 kg", flattened_cells)
        self.assertIn("R$ 16,25", flattened_cells)
