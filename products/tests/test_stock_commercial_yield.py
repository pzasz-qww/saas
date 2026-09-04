from django.test import TestCase
from django.urls import reverse

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
        self.assertContains(response, "50 mL por dose")
        self.assertContains(response, "90 doses completas")

    def test_pre_portioned_yield_is_explicitly_only_mathematical(self):
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

        self.assertContains(response, "12 porções completas")
        self.assertContains(response, "sobra 200 g")
        self.assertContains(response, "não indica porções já prontas")
