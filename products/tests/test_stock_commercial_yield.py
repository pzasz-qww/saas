from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from products.models import ProductComponent

from .helpers import make_company, make_entry, make_product, make_user


class StockCommercialYieldTests(TestCase):
    def setUp(self):
        self.company = make_company()
        self.user = make_user(company=self.company, role="owner")
        self.client.force_login(self.user)

    def test_dashboard_shows_dose_equivalent_from_physical_stock(self):
        product = make_product(
            company=self.company,
            name="Vodka em dose",
            sale_form="dose",
            stock_dimension="volume",
            dose_ml="50",
        )
        make_entry(product=product, quantity="4500")

        response = self.client.get(reverse("products:stock_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Estoque físico")
        self.assertContains(response, "4,5 L")
        self.assertContains(response, "Dose: 50 mL")
        self.assertContains(response, "Rende 90 doses")

    def test_pre_portioned_own_stock_is_reported_as_ready_for_sale(self):
        product = make_product(
            company=self.company,
            name="Batata pré-porcionada",
            inventory_role="prepared",
            sale_form="portion",
            stock_dimension="weight",
            portion_g="400",
            preparation_mode="pre_portioned",
        )
        make_entry(product=product, quantity="5000")

        response = self.client.get(reverse("products:stock_dashboard"))

        self.assertContains(response, "12 prontas para venda")
        self.assertContains(response, "Estoque físico: 5 kg")
        self.assertContains(
            response,
            "Cadastre ao menos um ingrediente antes de vender ou produzir este produto.",
        )

    def test_on_demand_dashboard_shows_limiting_ingredient_and_yields(self):
        drink = make_product(
            company=self.company,
            name="Caipirinha",
            inventory_role="prepared",
            preparation_mode="on_demand",
        )
        spirit = make_product(
            company=self.company,
            name="Cachaça",
            inventory_role="input",
            product_type="internal_use",
            stock_dimension="volume",
        )
        lemon = make_product(
            company=self.company,
            name="Limão",
            inventory_role="input",
            product_type="internal_use",
            stock_dimension="weight",
        )
        ProductComponent.objects.create(
            company=self.company,
            product=drink,
            ingredient=spirit,
            quantity=Decimal("50"),
            unit="mL",
        )
        ProductComponent.objects.create(
            company=self.company,
            product=drink,
            ingredient=lemon,
            quantity=Decimal("80"),
            unit="g",
        )
        make_entry(product=spirit, quantity="1000")
        make_entry(product=lemon, quantity="640")

        response = self.client.get(reverse("products:stock_dashboard"))

        self.assertContains(response, "8 disponíveis")
        self.assertContains(response, "Limitado por")
        self.assertContains(response, "Limão")
        self.assertContains(response, "Cachaça:")
        self.assertContains(response, "50 mL por item")
        self.assertContains(response, "rende 20")
        self.assertNotContains(response, "Esgotado por ingrediente")
