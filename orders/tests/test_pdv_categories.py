from django.test import TestCase
from django.urls import reverse

from products.category_services import resolve_category

from .helpers import (
    make_company,
    make_product,
    make_unit,
    make_user,
)


class PdvStructuredCategoryTests(TestCase):
    def setUp(self):
        self.company = make_company(name="Empresa principal")
        self.user = make_user(company=self.company)
        self.unit = make_unit(company=self.company)
        self.client.force_login(self.user)

    def test_products_are_grouped_by_visible_category_with_empty_fallback(self):
        category = resolve_category(
            company=self.company,
            raw_name="Bebidas sem álcool",
        )
        categorized = make_product(
            company=self.company,
            unit=self.unit,
            category=category,
            name="Suco",
        )
        uncategorized = make_product(
            company=self.company,
            unit=self.unit,
            category_name=None,
            name="Produto avulso",
        )

        response = self.client.get(reverse("orders:pdv"))

        self.assertEqual(response.status_code, 200)
        categories = response.context["categories"]
        self.assertIn("Bebidas sem álcool", categories)
        self.assertIn("Sem categoria", categories)
        self.assertIn(categorized, categories["Bebidas sem álcool"])
        self.assertIn(uncategorized, categories["Sem categoria"])
        self.assertContains(response, "Bebidas sem álcool")
        self.assertContains(response, "Sem categoria")

    def test_category_groups_are_ordered_by_name_instead_of_foreign_key_id(self):
        category_z = resolve_category(
            company=self.company,
            raw_name="Z Destilados",
        )
        category_a = resolve_category(
            company=self.company,
            raw_name="A Bebidas",
        )
        self.assertLess(category_z.pk, category_a.pk)
        make_product(
            company=self.company,
            unit=self.unit,
            category=category_z,
            name="Produto Z",
        )
        make_product(
            company=self.company,
            unit=self.unit,
            category=category_a,
            name="Produto A",
        )

        response = self.client.get(reverse("orders:pdv"))
        category_names = list(response.context["categories"])

        self.assertLess(
            category_names.index("A Bebidas"),
            category_names.index("Z Destilados"),
        )

    def test_pdv_keeps_existing_saleable_types_and_hides_internal_use(self):
        sale = make_product(
            company=self.company,
            unit=self.unit,
            name="Produto sale",
            product_type="sale",
        )
        both = make_product(
            company=self.company,
            unit=self.unit,
            name="Produto both",
            product_type="both",
        )
        internal = make_product(
            company=self.company,
            unit=self.unit,
            name="Produto internal_use",
            product_type="internal_use",
        )

        response = self.client.get(reverse("orders:pdv"))

        self.assertContains(response, sale.name)
        self.assertContains(response, both.name)
        self.assertNotContains(response, internal.name)

    def test_pdv_never_exposes_products_or_categories_from_another_company(self):
        foreign_company = make_company(name="Empresa confidencial")
        foreign_category = resolve_category(
            company=foreign_company,
            raw_name="Categoria confidencial",
        )
        foreign_product = make_product(
            company=foreign_company,
            category=foreign_category,
            name="Produto confidencial",
        )

        response = self.client.get(reverse("orders:pdv"))

        self.assertNotContains(response, foreign_category.name)
        self.assertNotContains(response, foreign_product.name)
        self.assertNotIn(
            foreign_category.name,
            response.context["categories"],
        )
