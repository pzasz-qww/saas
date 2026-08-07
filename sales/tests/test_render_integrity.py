"""Testes de integridade de vendas portados integralmente da render."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from companies.models import Company
from products.models import Product, StockMovement, Unit
from sales.models import Sale, SaleItem


class SaleTenantIntegrityTests(TestCase):
    def setUp(self):
        self.company_a = Company.objects.create(name="Praça Kennedy")
        self.company_b = Company.objects.create(name="Bar Aurora")
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
        self.sale_a = Sale.objects.create(
            company=self.company_a,
            payment_method="pix",
        )

    def test_sale_item_rejects_product_from_another_company(self):
        with self.assertRaises(ValidationError):
            SaleItem.objects.create(
                sale=self.sale_a,
                company=self.company_a,
                product=self.product_b,
                quantity=Decimal("1.00"),
            )

        self.assertFalse(SaleItem.objects.filter(sale=self.sale_a).exists())
        self.assertFalse(StockMovement.objects.exists())

    def test_sale_item_rejects_explicit_company_from_another_tenant(self):
        with self.assertRaises(ValidationError):
            SaleItem.objects.create(
                sale=self.sale_a,
                company=self.company_b,
                product=self.product_a,
                quantity=Decimal("1.00"),
            )

        self.assertFalse(SaleItem.objects.filter(sale=self.sale_a).exists())

    def test_sale_rejects_invalid_payment_method(self):
        with self.assertRaises(ValidationError):
            Sale.objects.create(
                company=self.company_a,
                payment_method="metodo-forjado",
            )

    def test_sale_item_rejects_non_positive_quantity(self):
        with self.assertRaises(ValidationError):
            SaleItem.objects.create(
                sale=self.sale_a,
                company=self.company_a,
                product=self.product_a,
                quantity=Decimal("-1.00"),
            )

        self.assertFalse(SaleItem.objects.filter(sale=self.sale_a).exists())
        self.assertFalse(StockMovement.objects.exists())
