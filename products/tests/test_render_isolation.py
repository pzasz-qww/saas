"""Testes de isolamento de produtos portados integralmente da render."""

from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.models import Profile
from companies.models import Company
from products.models import Product, StockEntry, StockMovement, Unit
from products.views import stock_report_products_for_company


class ProductTenantIsolationTests(TestCase):
    def setUp(self):
        self.company_a = Company.objects.create(name="Praça Kennedy")
        self.company_b = Company.objects.create(name="Bar Aurora")

        self.user_a = User.objects.create_user(
            username="dono_pk",
            password="senha-segura",
        )
        Profile.objects.create(
            user=self.user_a,
            company=self.company_a,
            role="owner",
        )

        self.unit_a = Unit.objects.create(
            company=self.company_a,
            name="Unidade",
            symbol="un-pk",
        )
        self.unit_b = Unit.objects.create(
            company=self.company_b,
            name="Unidade",
            symbol="un-aurora",
        )
        self.product_a = Product.objects.create(
            company=self.company_a,
            name="Heineken PK",
            unit=self.unit_a,
            sale_price=Decimal("12.00"),
        )
        self.product_b = Product.objects.create(
            company=self.company_b,
            name="Coca Aurora",
            unit=self.unit_b,
            sale_price=Decimal("8.00"),
        )
        self.entry_a = StockEntry.objects.create(
            company=self.company_a,
            product=self.product_a,
            total_cost=Decimal("50.00"),
            quantity_added=Decimal("10.00"),
        )
        self.entry_b = StockEntry.objects.create(
            company=self.company_b,
            product=self.product_b,
            total_cost=Decimal("30.00"),
            quantity_added=Decimal("10.00"),
        )

        self.client.force_login(self.user_a)

    def test_stock_dashboard_lists_only_current_company_products(self):
        response = self.client.get(reverse("products:stock_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Heineken PK")
        self.assertNotContains(response, "Coca Aurora")

    def test_stock_entry_rejects_product_from_another_company(self):
        initial_entries = StockEntry.objects.count()

        response = self.client.post(
            reverse("products:stock_entry_create"),
            {
                "product": self.product_b.pk,
                "entry_mode": "simple",
                "total_cost": "20.00",
                "quantity_added": "5.00",
            },
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(StockEntry.objects.count(), initial_entries)
        self.entry_b.refresh_from_db()
        self.assertEqual(self.entry_b.remaining_quantity, Decimal("10.00"))

    def test_stock_count_rejects_product_from_another_company(self):
        initial_movements = StockMovement.objects.count()

        response = self.client.post(
            reverse("products:stock_count_adjust"),
            {
                "product": self.product_b.pk,
                "real_quantity": "2.00",
                "notes": "tentativa cruzada",
            },
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(StockMovement.objects.count(), initial_movements)
        self.entry_b.refresh_from_db()
        self.assertEqual(self.entry_b.remaining_quantity, Decimal("10.00"))

    def test_product_create_rejects_unit_from_another_company(self):
        response = self.client.post(
            reverse("products:product_create"),
            {
                "name": "Produto malicioso",
                "category": "Teste",
                "product_type": "sale",
                "unit": self.unit_b.pk,
                "sale_price": "10.00",
                "minimum_quantity": "0.00",
                "active": "on",
            },
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(Product.objects.filter(name="Produto malicioso").exists())

    def test_stock_report_uses_only_current_company_queryset(self):
        response = self.client.get(reverse("products:stock_report_pdf"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("estoque_geral_", response["Content-Disposition"])

    def test_stock_totals_ignore_legacy_entry_from_another_company(self):
        StockEntry.objects.filter(pk=self.entry_b.pk).update(
            product=self.product_a
        )

        report_product = stock_report_products_for_company(
            self.company_a
        ).get(pk=self.product_a.pk)

        self.assertEqual(report_product.report_current_stock, Decimal("10.00"))
        self.assertEqual(self.product_a.current_stock, Decimal("10.00"))

    def test_models_reject_cross_company_stock_relations(self):
        with self.assertRaises(ValidationError):
            Product.objects.create(
                company=self.company_a,
                name="Unidade cruzada",
                unit=self.unit_b,
            )

        with self.assertRaises(ValidationError):
            StockEntry.objects.create(
                company=self.company_a,
                product=self.product_b,
                total_cost=Decimal("10.00"),
                quantity_added=Decimal("1.00"),
            )

        with self.assertRaises(ValidationError):
            StockMovement.objects.create(
                company=self.company_a,
                product=self.product_b,
                movement_type="loss",
                quantity=Decimal("1.00"),
            )
