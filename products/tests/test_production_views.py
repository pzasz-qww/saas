from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

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

    def production_payload(self, *, planned="10", produced="8", action="confirm"):
        return {
            "action": action,
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

        self.assertContains(response, "Nenhuma unidade preparada.")
        self.assertContains(response, "Pode preparar +10")
        self.assertContains(response, "Limitado por: Carne")
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
        self.assertContains(response, "Pode preparar +6")

    def test_production_form_shows_theoretical_consumption_and_current_stock(self):
        response = self.client.get(
            reverse("products:production_create", args=[self.product.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Preparar — Porção de carne")
        self.assertContains(response, "Ingredientes necessários")
        self.assertContains(response, "Disponível")
        self.assertContains(response, "5 kg")
        self.assertContains(response, "Ajustar consumo e perdas")
        self.assertContains(response, "Quantidade realmente produzida")
        self.assertNotContains(
            response,
            'name="planned_quantity" value="10"',
            html=False,
        )
        self.assertNotContains(
            response,
            'name="produced_quantity" value="10"',
            html=False,
        )
        self.assertEqual(
            response.context["form"].initial["production_date"],
            timezone.localdate(),
        )

    def test_post_registers_production_and_redirects_to_traceable_history(self):
        payload = self.production_payload(action="preview")
        preview = self.client.post(
            reverse("products:production_create", args=[self.product.pk]),
            payload,
        )

        self.assertEqual(preview.status_code, 200)
        self.assertContains(preview, "Resumo da produção")
        self.assertContains(preview, "Custo estimado")
        self.assertFalse(Production.objects.exists())

        payload["action"] = "confirm"
        payload["preview_token"] = preview.context["production_preview"][
            "confirmation_token"
        ]
        response = self.client.post(
            reverse("products:production_create", args=[self.product.pk]),
            payload,
        )

        production = Production.objects.get()
        self.assertRedirects(
            response,
            f"{reverse('products:production_detail', args=[production.pk])}?registrada=1",
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
        self.assertContains(detail, "Perda")
        self.assertContains(detail, "500 g")
        self.assertContains(detail, "R$ 100,00")
        feedback = self.client.get(
            f"{reverse('products:production_detail', args=[production.pk])}?registrada=1"
        )
        self.assertContains(feedback, "Produção registrada")
        self.assertContains(feedback, "8 prontas para venda")

    def test_invalid_real_consumption_does_not_change_stock(self):
        payload = self.production_payload(action="preview")
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

    def test_custom_consumption_preview_and_confirmation_debit_only_once(self):
        payload = self.production_payload(planned="8", produced="7", action="preview")
        payload["consumption-0-actual_quantity"] = "4500"
        payload["consumption-0-loss_quantity"] = "500"

        preview = self.client.post(
            reverse("products:production_create", args=[self.product.pk]),
            payload,
        )

        self.meat_entry.refresh_from_db()
        self.assertEqual(preview.status_code, 200)
        self.assertContains(preview, "Resumo da produção")
        self.assertContains(preview, "87,5%")
        self.assertContains(preview, "4,5 kg")
        self.assertContains(preview, "07/09/2026")
        self.assertEqual(self.meat_entry.remaining_quantity, D("5000"))
        self.assertFalse(Production.objects.exists())

        payload["action"] = "confirm"
        payload["preview_token"] = preview.context["production_preview"][
            "confirmation_token"
        ]
        response = self.client.post(
            reverse("products:production_create", args=[self.product.pk]),
            payload,
        )

        production = Production.objects.get()
        consumption = production.consumptions.get()
        self.meat_entry.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(production.planned_quantity, D("8"))
        self.assertEqual(production.produced_quantity, D("7"))
        self.assertEqual(production.yield_percentage, D("87.5"))
        self.assertEqual(consumption.theoretical_quantity, D("4000"))
        self.assertEqual(consumption.actual_quantity, D("4500"))
        self.assertEqual(consumption.loss_quantity, D("500"))
        self.assertEqual(self.meat_entry.remaining_quantity, D("500"))
        self.assertEqual(
            consumption.stock_movements.get().quantity,
            D("4500"),
        )

    def test_yield_percentage_is_compact_in_preview_history_and_detail(self):
        preview_payload = self.production_payload(
            planned="7",
            produced="5",
            action="preview",
        )
        preview = self.client.post(
            reverse("products:production_create", args=[self.product.pk]),
            preview_payload,
        )
        self.assertContains(preview, "71,4%")
        self.assertNotContains(preview, "71,428571")

        result = create_production(
            company=self.company,
            product=self.product,
            planned_quantity=D("9"),
            produced_quantity=D("8"),
            created_by=self.user,
        )
        history = self.client.get(reverse("products:production_list"))
        detail = self.client.get(
            reverse("products:production_detail", args=[result.production.pk])
        )
        for response in (history, detail):
            self.assertContains(response, "88,9%")
            self.assertNotContains(response, "88,888888")

    def test_confirmation_cannot_skip_or_change_the_reviewed_summary(self):
        direct_confirmation = self.client.post(
            reverse("products:production_create", args=[self.product.pk]),
            self.production_payload(action="confirm"),
        )
        self.assertEqual(direct_confirmation.status_code, 200)
        self.assertContains(
            direct_confirmation,
            "Revise o resumo novamente antes de registrar a produção.",
        )
        self.assertFalse(Production.objects.exists())

        payload = self.production_payload(action="preview")
        preview = self.client.post(
            reverse("products:production_create", args=[self.product.pk]),
            payload,
        )
        payload["action"] = "confirm"
        payload["produced_quantity"] = "7"
        payload["preview_token"] = preview.context["production_preview"][
            "confirmation_token"
        ]
        changed_confirmation = self.client.post(
            reverse("products:production_create", args=[self.product.pk]),
            payload,
        )

        self.assertContains(
            changed_confirmation,
            "Revise o resumo novamente antes de registrar a produção.",
        )
        self.assertFalse(Production.objects.exists())

    def test_detail_requires_explicit_reversal_confirmation(self):
        result = create_production(
            company=self.company,
            product=self.product,
            planned_quantity=D("2"),
            produced_quantity=D("2"),
            created_by=self.user,
        )

        response = self.client.get(
            reverse("products:production_detail", args=[result.production.pk])
        )

        self.assertContains(response, "Desfazer esta produção?")
        self.assertContains(response, "Os ingredientes retornarão aos lotes originais")
        self.assertContains(response, 'id="reversal-dialog"', html=False)
        result.production.refresh_from_db()
        self.assertEqual(result.production.status, "completed")

    def test_history_has_mobile_cards_with_operational_summary(self):
        result = create_production(
            company=self.company,
            product=self.product,
            planned_quantity=D("2"),
            produced_quantity=D("1"),
            created_by=self.user,
        )

        response = self.client.get(reverse("products:production_list"))

        self.assertContains(response, 'class="production-history-mobile"', html=False)
        self.assertContains(response, "1 produzidas")
        self.assertContains(response, "Rendimento")
        self.assertContains(
            response,
            reverse("products:production_detail", args=[result.production.pk]),
        )

    def test_foreign_company_cannot_view_or_produce_product(self):
        other_company = make_company(name="Outro bar")
        other_user = make_user(company=other_company, role="owner")
        self.client.force_login(other_user)

        response = self.client.get(
            reverse("products:production_create", args=[self.product.pk])
        )

        self.assertEqual(response.status_code, 404)
        filtered_history = self.client.get(
            f"{reverse('products:production_list')}?produto={self.product.pk}"
        )
        self.assertEqual(filtered_history.status_code, 404)
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
