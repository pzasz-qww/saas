from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from products import views as product_views

from .helpers import (
    make_category,
    make_company,
    make_product,
    make_unit,
    make_user,
)


class CategoryDisplayTests(TestCase):
    def setUp(self):
        self.company = make_company(name="Empresa principal")
        self.user = make_user(company=self.company)
        self.unit = make_unit(company=self.company)
        self.category = make_category(company=self.company, name="Porções")
        self.categorized = make_product(
            company=self.company,
            unit=self.unit,
            category=self.category,
            name="Batata categorizada",
            minimum_quantity="5.00",
        )
        self.uncategorized = make_product(
            company=self.company,
            unit=self.unit,
            category_name=None,
            name="Produto sem categoria",
            minimum_quantity="5.00",
        )

        other_company = make_company(name="Empresa estrangeira")
        foreign_category = make_category(
            company=other_company,
            name="Categoria secreta",
        )
        make_product(
            company=other_company,
            category=foreign_category,
            name="Produto secreto",
            minimum_quantity="5.00",
        )
        self.client.force_login(self.user)

    def test_dashboard_displays_category_and_friendly_empty_fallback(self):
        response = self.client.get(reverse("products:stock_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Porções")
        self.assertContains(response, "Sem categoria")
        self.assertContains(response, 'data-category="Porções"', html=False)
        self.assertContains(response, 'data-category=""', html=False)
        self.assertNotContains(response, "Categoria secreta")
        self.assertNotContains(response, "Produto secreto")

        queryset = response.context["products"]
        self.assertIn("category", queryset.query.select_related)

    def test_shopping_list_rows_expose_visible_category_names(self):
        response = self.client.get(reverse("products:shopping_list"))

        self.assertEqual(response.status_code, 200)
        categories_by_product = {
            row["product"].name: row["category"]
            for row in response.context["rows"]
        }
        self.assertEqual(
            categories_by_product[self.categorized.name],
            "Porções",
        )
        self.assertEqual(
            categories_by_product[self.uncategorized.name],
            "Sem categoria",
        )
        self.assertNotIn("Produto secreto", categories_by_product)

    def test_stock_entry_and_count_cards_use_visible_name_or_empty_data_value(self):
        for url_name in (
            "products:stock_entry_create",
            "products:stock_count_adjust",
        ):
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(url_name))

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Porções")
                self.assertContains(response, "Sem categoria")
                self.assertContains(
                    response,
                    'data-category="Porções"',
                    html=False,
                )
                self.assertContains(
                    response,
                    'data-category=""',
                    html=False,
                )
                self.assertIn(
                    "category",
                    response.context["products"].query.select_related,
                )

    def test_pdf_receives_category_name_and_empty_fallback(self):
        captured_paragraphs = []
        real_paragraph = product_views.Paragraph

        def capture_paragraph(text, style, *args, **kwargs):
            captured_paragraphs.append(text)
            return real_paragraph(text, style, *args, **kwargs)

        with patch(
            "products.views.Paragraph",
            side_effect=capture_paragraph,
        ):
            response = self.client.get(reverse("products:stock_report_pdf"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertIn("Porções", captured_paragraphs)
        self.assertIn("Sem categoria", captured_paragraphs)
        self.assertNotIn("Categoria secreta", captured_paragraphs)

    def test_category_html_is_escaped_in_dashboard_data_and_visible_text(self):
        malicious = make_category(
            company=self.company,
            name='<script>window.categoryXss=1</script> "',
        )
        make_product(
            company=self.company,
            unit=self.unit,
            category=malicious,
            name="Produto de categoria maliciosa",
        )

        response = self.client.get(reverse("products:stock_dashboard"))
        html = response.content.decode("utf-8")

        self.assertNotIn("<script>window.categoryXss=1</script>", html)
        self.assertIn("&lt;script&gt;window.categoryXss=1&lt;/script&gt;", html)

    def test_category_javascript_does_not_interpolate_database_names_as_html(self):
        for script_name in (
            "stock_dashboard.js",
            "stock_entry_form.js",
            "stock_count_form.js",
            "pdv.js",
        ):
            with self.subTest(script_name=script_name):
                script = Path(
                    settings.BASE_DIR,
                    "static",
                    "js",
                    script_name,
                ).read_text(encoding="utf-8")

                self.assertNotIn("innerHTML", script)
                self.assertIn("textContent", script)
