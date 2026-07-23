from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from products.category_services import resolve_category
from products.models import Category, Product

from .helpers import make_company, make_unit, make_user


class ProductCategoryCreateViewTests(TestCase):
    def setUp(self):
        self.company = make_company(name="Empresa principal")
        self.user = make_user(company=self.company)
        self.unit = make_unit(company=self.company)
        self.client.force_login(self.user)

    def product_payload(self, **overrides):
        payload = {
            "name": "Produto cadastrado",
            "category": "Bebidas",
            "product_type": "sale",
            "unit": str(self.unit.pk),
            "sale_price": "12.50",
            "minimum_quantity": "3",
            "active": "on",
        }
        payload.update(overrides)
        return payload

    def post_product(self, **overrides):
        return self.client.post(
            reverse("products:product_create"),
            self.product_payload(**overrides),
        )

    def test_existing_equivalent_category_is_reused(self):
        category = resolve_category(
            company=self.company,
            raw_name="Porções",
        )

        response = self.post_product(category="  Porcoes  ")

        self.assertRedirects(
            response,
            reverse("products:stock_dashboard"),
            fetch_redirect_response=False,
        )
        product = Product.objects.get()
        self.assertEqual(product.category_id, category.pk)
        self.assertEqual(product.category_legacy, "Porcoes")
        self.assertEqual(Category.objects.count(), 1)

    def test_new_category_is_created_for_the_authenticated_company(self):
        response = self.post_product(category="  Bebidas   sem álcool  ")

        self.assertEqual(response.status_code, 302)
        product = Product.objects.select_related("category").get()
        self.assertEqual(product.company, self.company)
        self.assertEqual(product.category.company, self.company)
        self.assertEqual(product.category.name, "Bebidas sem álcool")
        self.assertEqual(product.category.normalized_name, "bebidas sem alcool")
        self.assertEqual(product.category_legacy, "Bebidas sem álcool")

    def test_empty_category_keeps_product_valid_with_null_foreign_key(self):
        response = self.post_product(category="   ")

        self.assertEqual(response.status_code, 302)
        product = Product.objects.get()
        self.assertIsNone(product.category_id)
        self.assertIsNone(product.category_legacy)
        self.assertFalse(Category.objects.exists())

    def test_posted_company_is_ignored_and_category_is_created_locally(self):
        other_company = make_company(name="Empresa estrangeira")
        foreign_category = resolve_category(
            company=other_company,
            raw_name="Bebidas",
        )

        response = self.post_product(
            company=str(other_company.pk),
            category=foreign_category.name,
        )

        self.assertEqual(response.status_code, 302)
        product = Product.objects.select_related("category").get()
        self.assertEqual(product.company, self.company)
        self.assertEqual(product.category.company, self.company)
        self.assertNotEqual(product.category_id, foreign_category.pk)

    def test_forged_foreign_category_id_is_rejected_without_data_leak(self):
        other_company = make_company(name="Empresa confidencial")
        foreign_category = resolve_category(
            company=other_company,
            raw_name="Categoria confidencial",
        )

        response = self.post_product(
            category="Categoria local que não deve existir",
            category_id=str(foreign_category.pk),
            company=str(other_company.pk),
        )
        message_text = "\n".join(
            str(message) for message in get_messages(response.wsgi_request)
        )

        self.assertRedirects(
            response,
            reverse("products:product_create"),
            fetch_redirect_response=False,
        )
        self.assertIn("dados informados", message_text.lower())
        self.assertNotIn(foreign_category.name, message_text)
        self.assertNotIn(other_company.name, message_text)
        self.assertFalse(Product.objects.exists())
        self.assertFalse(
            Category.objects.filter(company=self.company).exists()
        )

    def test_all_existing_product_types_are_accepted(self):
        for product_type in ("sale", "internal_use", "both"):
            with self.subTest(product_type=product_type):
                response = self.post_product(
                    name=f"Produto {product_type}",
                    category="",
                    product_type=product_type,
                )
                self.assertEqual(response.status_code, 302)

        self.assertCountEqual(
            Product.objects.values_list("product_type", flat=True),
            ["sale", "internal_use", "both"],
        )

    def test_forged_product_types_are_rejected_without_orphan_category(self):
        for product_type in ("external_consumption", "", "forged"):
            with self.subTest(product_type=product_type):
                response = self.post_product(
                    name=f"Inválido {product_type}",
                    category="Categoria órfã",
                    product_type=product_type,
                )
                self.assertRedirects(
                    response,
                    reverse("products:product_create"),
                    fetch_redirect_response=False,
                )

        self.assertFalse(Product.objects.exists())
        self.assertFalse(Category.objects.exists())

