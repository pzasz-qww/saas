from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from products.models import ProductComponent, Production, StockEntry
from products.production_services import create_production

from .helpers import make_company, make_entry, make_product, make_user


D = Decimal


class ProductionViewTests(TestCase):
    def setUp(self):
        self.company = make_company(name="Bar Interface")
        self.user = make_user(company=self.company, role="owner")
        self.client.force_login(self.user)
        self.product = make_product(
            company=self.company,
            name="Porção de carne",
            inventory_role="prepared",
            preparation_mode="pre_portioned",
        )
        self.meat = make_product(
            company=self.company,
            name="Carne",
            inventory_role="input",
            product_type="internal_use",
            stock_dimension="weight",
        )
        self.component = ProductComponent.objects.create(
            company=self.company,
            product=self.product,
            ingredient=self.meat,
            quantity=D("500"),
            unit="g",
        )
        self.meat_entry = make_entry(
            product=self.meat,
            quantity="5000",
            total_cost="100",
        )

    def production_payload(self, *, planned="10", produced="8"):
        return {
            "planned_quantity": planned,
            "produced_quantity": produced,
            "production_date": "2026-09-05",
            "expiration_date": "2026-09-07",
            "notes": "Produção da manhã",
            "consumption-TOTAL_FORMS": "1",
            "consumption-INITIAL_FORMS": "0",
            "consumption-MIN_NUM_FORMS": "0",
            "consumption-MAX_NUM_FORMS": "1000",
            "consumption-0-component_id": str(self.component.pk),
            "consumption-0-actual_quantity": "5000",
            "consumption-0-loss_quantity": "500",
        }

    def test_stock_dashboard_separates_ready_stock_and_production_potential(self):
        response = self.client.get(reverse("products:stock_dashboard"))

        self.assertContains(response, "0 prontas para venda")
        self.assertContains(response, "Pode preparar: +10")
        self.assertContains(response, "Limitado por Carne")
        self.assertContains(
            response,
            reverse("products:production_create", args=[self.product.pk]),
        )

        create_production(
            company=self.company,
            product=self.product,
            planned_quantity=D("4"),
            produced_quantity=D("3"),
            created_by=self.user,
        )
        response = self.client.get(reverse("products:stock_dashboard"))
        self.assertContains(response, "3 prontas para venda")
        self.assertContains(response, "Pode preparar: +6")

    def test_production_form_shows_theoretical_consumption_and_current_stock(self):
        response = self.client.get(
            reverse("products:production_create", args=[self.product.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Produzir — Porção de carne")
        self.assertContains(response, "Consumo previsto:")
        self.assertContains(response, "5 kg")
        self.assertContains(response, "Estoque suficiente")
        self.assertContains(response, "Quantidade realmente produzida")

    def test_post_registers_production_and_redirects_to_traceable_history(self):
        response = self.client.post(
            reverse("products:production_create", args=[self.product.pk]),
            self.production_payload(),
        )

        production = Production.objects.get()
        self.assertRedirects(
            response,
            reverse("products:production_detail", args=[production.pk]),
        )
        self.assertEqual(production.produced_quantity, D("8"))
        self.assertEqual(production.consumptions.get().loss_quantity, D("500"))
        output = StockEntry.objects.get(production=production)
        self.assertEqual(output.remaining_quantity, D("8"))
        detail = self.client.get(
            reverse("products:production_detail", args=[production.pk])
        )
        self.assertContains(detail, "Produção #")
        self.assertContains(detail, "Lote #")
        self.assertContains(detail, "Perda: 500 g")
        self.assertContains(detail, "R$ 100,00")

    def test_invalid_real_consumption_does_not_change_stock(self):
        payload = self.production_payload()
        payload["consumption-0-actual_quantity"] = "6000"

        response = self.client.post(
            reverse("products:production_create", args=[self.product.pk]),
            payload,
        )

        self.meat_entry.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Estoque insuficiente")
        self.assertEqual(self.meat_entry.remaining_quantity, D("5000"))
        self.assertFalse(Production.objects.exists())

    def test_foreign_company_cannot_view_or_produce_product(self):
        other_company = make_company(name="Outro bar")
        other_user = make_user(company=other_company, role="owner")
        self.client.force_login(other_user)

        response = self.client.get(
            reverse("products:production_create", args=[self.product.pk])
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(Production.objects.exists())

    def test_reverse_action_marks_production_and_removes_ready_lot(self):
        result = create_production(
            company=self.company,
            product=self.product,
            planned_quantity=D("10"),
            produced_quantity=D("8"),
            created_by=self.user,
        )

        response = self.client.post(
            reverse("products:production_reverse", args=[result.production.pk])
        )

        result.production.refresh_from_db()
        result.output_entry.refresh_from_db()
        self.meat_entry.refresh_from_db()
        self.assertRedirects(
            response,
            reverse("products:production_detail", args=[result.production.pk]),
        )
        self.assertEqual(result.production.status, "reversed")
        self.assertEqual(result.output_entry.remaining_quantity, D("0"))
        self.assertEqual(self.meat_entry.remaining_quantity, D("5000"))

    def test_user_without_stock_adjust_permission_cannot_produce_or_reverse(self):
        result = create_production(
            company=self.company,
            product=self.product,
            planned_quantity=D("10"),
            produced_quantity=D("8"),
            created_by=self.user,
        )
        waiter = make_user(company=self.company, role="waiter")
        self.client.force_login(waiter)
        response = self.client.post(
            reverse("products:production_create", args=[self.product.pk]),
            self.production_payload(),
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("products:stock_dashboard"))
        reverse_response = self.client.post(
            reverse("products:production_reverse", args=[result.production.pk])
        )
        self.assertEqual(reverse_response.status_code, 302)
        self.assertEqual(
            reverse_response.url,
            reverse("products:production_detail", args=[result.production.pk]),
        )
        result.production.refresh_from_db()
        self.assertEqual(result.production.status, "completed")
        self.assertEqual(Production.objects.count(), 1)
