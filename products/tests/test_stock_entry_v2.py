from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from products.models import StockEntry
from products.services import (
    InvalidStockOperation,
    StockEntryValidationError,
    apply_negative_adjustment,
    apply_stock_count,
    create_stock_entry,
)

from .helpers import make_company, make_product, make_unit, make_user


class StockEntryServiceV2Tests(TestCase):
    def setUp(self):
        self.company = make_company(name="Empresa Entrada 2")
        self.unit = make_unit(company=self.company, name="Unidade legado")
        self.count_product = make_product(
            company=self.company,
            unit=self.unit,
            name="Papel higienico",
            stock_dimension="count",
        )
        self.weight_product = make_product(
            company=self.company,
            unit=self.unit,
            name="Carne",
            stock_dimension="weight",
        )
        self.volume_product = make_product(
            company=self.company,
            unit=self.unit,
            name="Xarope",
            stock_dimension="volume",
        )
        self.user = make_user(company=self.company, username="estoquista-v2")

    def create_entry(self, *, product, quantity, unit, mode="total", price="10", **extra):
        return create_stock_entry(
            company=self.company,
            product=product,
            input_quantity=quantity,
            input_unit=unit,
            price_mode=mode,
            price=price,
            created_by=self.user,
            **extra,
        )

    def test_normalizes_supported_quantities_and_preserves_original_input(self):
        cases = (
            (self.weight_product, "30", "kg", Decimal("30000"), "g"),
            (self.weight_product, "750", "mg", Decimal("0.750"), "g"),
            (self.volume_product, "5", "L", Decimal("5000"), "mL"),
            (self.count_product, "20", "unit", Decimal("20"), "unit"),
        )
        for product, quantity, unit, normalized, base_unit in cases:
            with self.subTest(quantity=quantity, unit=unit):
                entry = self.create_entry(
                    product=product,
                    quantity=quantity,
                    unit=unit,
                )
                self.assertEqual(entry.input_quantity, Decimal(quantity))
                self.assertEqual(entry.input_unit, unit)
                self.assertEqual(entry.normalized_quantity, normalized)
                self.assertEqual(entry.base_unit, base_unit)
                self.assertEqual(entry.remaining_quantity, normalized)

    def test_direct_input_and_internal_use_products_accept_entries(self):
        input_product = make_product(
            company=self.company,
            unit=self.unit,
            name="Insumo",
            inventory_role="input",
            product_type="internal_use",
            stock_dimension="weight",
        )
        internal_product = make_product(
            company=self.company,
            unit=self.unit,
            name="Material interno",
            product_type="internal_use",
            stock_dimension="count",
        )
        cases = (
            (self.count_product, "unit"),
            (input_product, "kg"),
            (internal_product, "unit"),
        )
        for product, unit in cases:
            with self.subTest(product=product.name):
                entry = self.create_entry(product=product, quantity="1", unit=unit)
                self.assertEqual(entry.product, product)

    def test_total_price_derives_exact_normalized_unit_cost(self):
        entry = self.create_entry(
            product=self.weight_product,
            quantity="30",
            unit="kg",
            price="750",
        )

        self.assertEqual(entry.total_cost, Decimal("750"))
        self.assertEqual(entry.normalized_unit_cost, Decimal("0.025"))
        self.assertEqual(
            entry.normalized_unit_cost / Decimal("1000"),
            Decimal("0.000025"),
        )

    def test_price_per_measure_calculates_total_for_weight_volume_and_count(self):
        cases = (
            (self.weight_product, "30", "kg", "25", Decimal("750"), Decimal("0.025")),
            (self.volume_product, "5", "L", "18", Decimal("90"), Decimal("0.018")),
            (self.count_product, "20", "unit", "2.50", Decimal("50.00"), Decimal("2.50")),
        )
        for product, quantity, unit, price, total, normalized_cost in cases:
            with self.subTest(product=product.name):
                entry = self.create_entry(
                    product=product,
                    quantity=quantity,
                    unit=unit,
                    mode="per_unit",
                    price=price,
                )
                self.assertEqual(entry.total_cost, total)
                self.assertEqual(entry.normalized_unit_cost, normalized_cost)

    def test_expiration_is_optional_and_each_lot_keeps_its_own_date(self):
        first_date = timezone.localdate() + timedelta(days=3)
        second_date = timezone.localdate() + timedelta(days=8)
        first = self.create_entry(
            product=self.weight_product,
            quantity="10",
            unit="kg",
            expiration_date=first_date,
        )
        second = self.create_entry(
            product=self.weight_product,
            quantity="20",
            unit="kg",
            expiration_date=second_date,
        )
        no_expiration = self.create_entry(
            product=self.weight_product,
            quantity="5",
            unit="kg",
        )

        self.assertEqual(first.expiration_date, first_date)
        self.assertEqual(second.expiration_date, second_date)
        self.assertIsNone(no_expiration.expiration_date)

    def test_past_expiration_is_recorded_without_discard_or_fefo(self):
        past_date = timezone.localdate() - timedelta(days=1)
        entry = self.create_entry(
            product=self.weight_product,
            quantity="1",
            unit="kg",
            expiration_date=past_date,
        )
        self.assertEqual(entry.expiration_date, past_date)
        self.assertEqual(entry.remaining_quantity, Decimal("1000"))

    def test_entry_date_defaults_to_today_and_accepts_manual_date(self):
        defaulted = self.create_entry(
            product=self.count_product,
            quantity="1",
            unit="unit",
        )
        informed_date = date(2026, 8, 20)
        informed = self.create_entry(
            product=self.count_product,
            quantity="1",
            unit="unit",
            entry_date=informed_date,
        )
        self.assertEqual(defaulted.entry_date, timezone.localdate())
        self.assertEqual(informed.entry_date, informed_date)

    def test_unit_compatibility_rules_are_enforced_server_side(self):
        valid_cases = (
            (self.weight_product, "kg"),
            (self.volume_product, "L"),
            (self.count_product, "unit"),
        )
        for product, unit in valid_cases:
            with self.subTest(product=product.name, unit=unit):
                self.create_entry(product=product, quantity="1", unit=unit)

        invalid_cases = (
            (self.weight_product, "L"),
            (self.volume_product, "kg"),
        )
        for product, unit in invalid_cases:
            with self.subTest(product=product.name, unit=unit):
                with self.assertRaisesMessage(
                    StockEntryValidationError,
                    "A unidade informada \u00e9 incompat\u00edvel",
                ):
                    self.create_entry(product=product, quantity="1", unit=unit)

    def test_invalid_quantity_price_and_dates_have_specific_errors(self):
        invalid_cases = (
            ({"input_quantity": "0"}, "A quantidade deve ser maior que zero."),
            ({"input_quantity": "-1"}, "A quantidade deve ser maior que zero."),
            ({"input_quantity": "NaN"}, "Informe uma quantidade v\u00e1lida."),
            ({"price": ""}, "Informe o pre\u00e7o da entrada."),
            ({"price": "Infinity"}, "Informe um pre\u00e7o v\u00e1lido."),
            ({"price": "-1"}, "O pre\u00e7o n\u00e3o pode ser negativo."),
            ({"entry_date": "31/99/2026"}, "Informe uma data da entrada v\u00e1lida."),
            ({"expiration_date": "amanha"}, "Informe uma validade v\u00e1lida."),
        )
        defaults = {
            "company": self.company,
            "product": self.count_product,
            "input_quantity": "1",
            "input_unit": "unit",
            "price_mode": "total",
            "price": "10",
        }
        for overrides, message in invalid_cases:
            with self.subTest(overrides=overrides):
                with self.assertRaisesMessage(StockEntryValidationError, message):
                    create_stock_entry(**(defaults | overrides))

    def test_new_entries_feed_existing_fifo_without_fefo_reordering(self):
        first = self.create_entry(
            product=self.weight_product,
            quantity="1",
            unit="kg",
            price="10",
            expiration_date=timezone.localdate() + timedelta(days=20),
        )
        second = self.create_entry(
            product=self.weight_product,
            quantity="2",
            unit="kg",
            price="40",
            expiration_date=timezone.localdate() + timedelta(days=2),
        )

        movements = apply_negative_adjustment(
            company=self.company,
            product=self.weight_product,
            quantity=Decimal("1500"),
        )

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.remaining_quantity, Decimal("0"))
        self.assertEqual(second.remaining_quantity, Decimal("1500"))
        self.assertEqual([movement.stock_entry_id for movement in movements], [first.id, second.id])

    def test_stock_count_uses_normalized_quantity(self):
        entry = self.create_entry(
            product=self.weight_product,
            quantity="30",
            unit="kg",
            price="750",
        )
        result = apply_stock_count(
            company=self.company,
            product=self.weight_product,
            real_quantity=Decimal("29500"),
        )
        entry.refresh_from_db()
        self.assertEqual(result.expected_quantity, Decimal("30000"))
        self.assertEqual(result.difference, Decimal("-500"))
        self.assertEqual(entry.remaining_quantity, Decimal("29500"))

    def test_product_from_another_company_is_rejected(self):
        other_company = make_company(name="Empresa externa")
        other_product = make_product(company=other_company, name="Produto externo")
        with self.assertRaises(InvalidStockOperation):
            self.create_entry(product=other_product, quantity="1", unit="unit")


class StockEntryViewV2Tests(TestCase):
    def setUp(self):
        self.company = make_company(name="Empresa da tela")
        self.product = make_product(
            company=self.company,
            name="Carne da tela",
            stock_dimension="weight",
        )
        self.owner = make_user(company=self.company, username="dono-entrada")
        self.client.force_login(self.owner)
        self.url = reverse("products:stock_entry_create")

    def valid_post(self, **overrides):
        data = {
            "product": str(self.product.pk),
            "input_quantity": "30",
            "input_unit": "kg",
            "price_mode": "per_unit",
            "price": "25,00",
            "entry_date": timezone.localdate().isoformat(),
            "expiration_date": "",
            "notes": "Compra semanal",
        }
        data.update(overrides)
        return data

    def test_interface_creates_normalized_lot_and_records_user(self):
        response = self.client.post(self.url, self.valid_post())
        self.assertRedirects(response, reverse("products:stock_dashboard"))
        entry = StockEntry.objects.get()
        self.assertEqual(entry.input_quantity, Decimal("30"))
        self.assertEqual(entry.input_unit, "kg")
        self.assertEqual(entry.quantity_added, Decimal("30000"))
        self.assertEqual(entry.total_cost, Decimal("750.00"))
        self.assertEqual(entry.created_by, self.owner)

    def test_success_message_preserves_input_unit_and_formats_total_cost(self):
        response = self.client.post(
            self.url,
            self.valid_post(
                input_quantity="5",
                price_mode="total",
                price="140",
            ),
            follow=True,
        )

        self.assertContains(
            response,
            "Entrada criada: Carne da tela recebeu 5 kg. "
            "Custo total: R$ 140,00.",
        )

    def test_invalid_post_preserves_values_and_shows_specific_errors(self):
        response = self.client.post(
            self.url,
            self.valid_post(input_quantity="0", price="-1"),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "A quantidade deve ser maior que zero.")
        self.assertContains(response, "O pre\u00e7o n\u00e3o pode ser negativo.")
        self.assertContains(response, "Carne da tela")
        self.assertContains(response, 'value="-1"', html=False)
        self.assertFalse(StockEntry.objects.exists())

    def test_incompatible_unit_and_malformed_product_are_field_errors(self):
        incompatible = self.client.post(
            self.url,
            self.valid_post(input_unit="L"),
        )
        self.assertEqual(incompatible.status_code, 200)
        self.assertContains(
            incompatible,
            "A unidade informada \u00e9 incompat\u00edvel com a dimens\u00e3o "
            "de estoque deste produto.",
        )

        malformed = self.client.post(
            self.url,
            self.valid_post(product="produto-invalido"),
        )
        self.assertEqual(malformed.status_code, 200)
        self.assertContains(malformed, "Selecione um produto v\u00e1lido.")
        self.assertFalse(StockEntry.objects.exists())

    def test_foreign_product_returns_404(self):
        other_company = make_company(name="Outra empresa da tela")
        foreign_product = make_product(company=other_company, name="Segredo")
        response = self.client.post(
            self.url,
            self.valid_post(product=str(foreign_product.pk)),
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(StockEntry.objects.exists())

    def test_user_without_permission_is_rejected(self):
        unauthorized = make_user(
            company=self.company,
            role="waiter",
            username="sem-permissao-entrada",
        )
        self.client.force_login(unauthorized)
        response = self.client.post(self.url, self.valid_post())
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("products:stock_dashboard"))
        self.assertFalse(StockEntry.objects.exists())

    def test_product_cards_expose_only_dimension_for_dynamic_units(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-dimension="weight"', html=False)
        self.assertContains(response, "Validade (opcional)")
        self.assertContains(response, "Data da entrada")

    def test_quick_entry_preselects_only_a_product_from_the_current_company(self):
        response = self.client.get(f"{self.url}?produto={self.product.pk}")

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'name="product" value="{self.product.pk}"',
            html=False,
        )
        self.assertContains(response, "Produto selecionado: Carne da tela")

        other_company = make_company(name="Empresa fora da entrada rápida")
        foreign_product = make_product(
            company=other_company,
            name="Produto de outra empresa",
        )
        foreign_response = self.client.get(
            f"{self.url}?produto={foreign_product.pk}"
        )
        self.assertEqual(foreign_response.status_code, 404)

    def test_stock_surfaces_show_the_normalized_base_unit(self):
        create_stock_entry(
            company=self.company,
            product=self.product,
            input_quantity="30",
            input_unit="kg",
            price_mode="total",
            price="750",
            created_by=self.owner,
        )

        dashboard = self.client.get(reverse("products:stock_dashboard"))
        count_form = self.client.get(reverse("products:stock_count_adjust"))
        self.assertContains(dashboard, "30 kg")
        self.assertContains(count_form, 'data-unit="g"', html=False)
        self.assertContains(count_form, 'data-stock-display="30 kg"', html=False)
        self.assertContains(count_form, "Estoque esperado: 30 kg")
