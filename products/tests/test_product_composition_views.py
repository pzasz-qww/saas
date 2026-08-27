from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from products.models import Product, ProductComponent, Unit

from .helpers import make_company, make_product, make_unit, make_user


class ProductCompositionCreateViewTests(TestCase):
    def setUp(self):
        self.company = make_company(name="Empresa principal")
        self.user = make_user(company=self.company, role="owner")
        self.client.force_login(self.user)

    def payload(self, **overrides):
        data = {
            "name": "Caipirinha",
            "sale_price": "18.00",
            "sale_form": "dose",
            "inventory_role": "prepared",
            "stock_dimension": "count",
            "preparation_mode": "on_demand",
            "active": "on",
            "active_present": "1",
            "components-TOTAL_FORMS": "0",
            "components-INITIAL_FORMS": "0",
            "components-MIN_NUM_FORMS": "0",
            "components-MAX_NUM_FORMS": "1000",
        }
        data.update(overrides)
        return data

    def test_quick_create_needs_no_preexisting_legacy_unit(self):
        response = self.client.post(
            reverse("products:product_create"),
            {
                "name": "Água",
                "sale_price": "5.00",
                "sale_form": "unit",
            },
        )

        self.assertEqual(response.status_code, 302)
        product = Product.objects.get()
        self.assertEqual(product.inventory_role, "direct")
        self.assertEqual(product.stock_dimension, "count")
        self.assertEqual(product.unit.symbol, "un")
        self.assertTrue(product.active)

    def test_prepared_product_can_be_saved_without_components(self):
        response = self.client.post(
            reverse("products:product_create"),
            self.payload(),
        )

        self.assertEqual(response.status_code, 302)
        product = Product.objects.get()
        self.assertEqual(product.inventory_role, "prepared")
        self.assertFalse(product.components.exists())

    def test_one_partial_component_is_saved_and_normalized(self):
        unit = make_unit(company=self.company)
        vodka = make_product(
            company=self.company,
            unit=unit,
            name="Vodka",
            inventory_role="input",
            stock_dimension="volume",
        )

        response = self.client.post(
            reverse("products:product_create"),
            self.payload(
                **{
                    "components-TOTAL_FORMS": "1",
                    "components-0-ingredient": str(vodka.pk),
                    "components-0-quantity": "0.05",
                    "components-0-unit": "L",
                }
            ),
        )

        self.assertEqual(response.status_code, 302)
        component = ProductComponent.objects.get()
        self.assertEqual(component.product.name, "Caipirinha")
        self.assertEqual(component.ingredient, vodka)
        self.assertEqual(component.quantity, Decimal("50.000000"))
        self.assertEqual(component.unit, "mL")

    def test_multiple_components_are_saved(self):
        unit = make_unit(company=self.company)
        vodka = make_product(
            company=self.company,
            unit=unit,
            name="Vodka",
            inventory_role="input",
            stock_dimension="volume",
        )
        lemon = make_product(
            company=self.company,
            unit=unit,
            name="Limão",
            inventory_role="input",
            stock_dimension="count",
        )

        response = self.client.post(
            reverse("products:product_create"),
            self.payload(
                **{
                    "components-TOTAL_FORMS": "2",
                    "components-0-ingredient": str(vodka.pk),
                    "components-0-quantity": "50",
                    "components-0-unit": "mL",
                    "components-1-ingredient": str(lemon.pk),
                    "components-1-quantity": "1",
                    "components-1-unit": "unit",
                }
            ),
        )

        self.assertEqual(response.status_code, 302)
        product = Product.objects.get(name="Caipirinha")
        self.assertEqual(product.components.count(), 2)

    def test_foreign_component_is_rejected_and_product_is_not_created(self):
        other_company = make_company(name="Empresa estrangeira")
        foreign = make_product(
            company=other_company,
            name="Ingrediente confidencial",
            inventory_role="input",
            stock_dimension="volume",
        )

        response = self.client.post(
            reverse("products:product_create"),
            self.payload(
                **{
                    "components-TOTAL_FORMS": "1",
                    "components-0-ingredient": str(foreign.pk),
                    "components-0-quantity": "50",
                    "components-0-unit": "mL",
                }
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Selecione um ingrediente válido.")
        self.assertFalse(Product.objects.filter(company=self.company).exists())
        self.assertFalse(ProductComponent.objects.exists())
        self.assertFalse(Unit.objects.filter(company=self.company).exists())

    def test_get_never_exposes_foreign_ingredients(self):
        own = make_product(
            company=self.company,
            name="Ingrediente local",
            inventory_role="input",
        )
        other_company = make_company(name="Outra empresa")
        foreign = make_product(
            company=other_company,
            name="Ingrediente confidencial",
            inventory_role="input",
        )

        response = self.client.get(reverse("products:product_create"))

        self.assertContains(response, own.name)
        self.assertNotContains(response, foreign.name)

    def test_user_without_permission_cannot_create_product_or_composition(self):
        unauthorized = make_user(
            company=self.company,
            role="waiter",
            username="sem-permissao",
        )
        self.client.force_login(unauthorized)

        response = self.client.post(
            reverse("products:product_create"),
            self.payload(),
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Product.objects.exists())
        self.assertFalse(ProductComponent.objects.exists())

    def test_basic_fields_are_visually_before_advanced_settings(self):
        response = self.client.get(reverse("products:product_create"))
        content = response.content.decode()

        self.assertLess(content.index('id="name"'), content.index("Configurações avançadas"))
        self.assertLess(content.index('id="sale_price"'), content.index("Configurações avançadas"))
        self.assertLess(content.index('id="sale_form"'), content.index("Configurações avançadas"))
