from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase

from companies.models import Company
from products.models import Product, StockEntry, StockMovement, Unit
from sales.models import Sale, SaleItem


class StockMovementIntegrityTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Empresa")
        self.unit = Unit.objects.create(
            company=self.company,
            name="Unidade",
            symbol="un",
        )
        self.product = Product.objects.create(
            company=self.company,
            name="Produto",
            unit=self.unit,
            sale_price=Decimal("10.00"),
        )
        self.entry = StockEntry.objects.create(
            company=self.company,
            product=self.product,
            total_cost=Decimal("20.00"),
            quantity_added=Decimal("10.00"),
        )
        self.sale = Sale.objects.create(
            company=self.company,
            payment_method="cash",
        )
        self.sale_item = SaleItem.objects.create(
            sale=self.sale,
            company=self.company,
            product=self.product,
            quantity=Decimal("2.00"),
            unit_price=Decimal("10.00"),
            unit_cost=Decimal("2.00"),
        )

    def create_sale_movement(self):
        return StockMovement.objects.create(
            company=self.company,
            product=self.product,
            stock_entry=self.entry,
            sale_item=self.sale_item,
            movement_type="sale",
            quantity=Decimal("2.00"),
        )

    def test_legacy_sale_movement_can_remain_without_new_links(self):
        movement = StockMovement.objects.create(
            company=self.company,
            product=self.product,
            movement_type="sale",
            quantity=Decimal("1.00"),
        )

        self.assertIsNone(movement.sale_item_id)
        self.assertIsNone(movement.reversal_of_id)
        self.assertIsNone(movement.stock_entry_id)

    def test_sale_item_and_entry_allocation_is_unique(self):
        self.create_sale_movement()

        with self.assertRaises(IntegrityError), transaction.atomic():
            self.create_sale_movement()

    def test_one_sale_movement_can_only_be_reversed_once(self):
        original = self.create_sale_movement()
        StockMovement.objects.create(
            company=self.company,
            product=self.product,
            stock_entry=self.entry,
            sale_item=self.sale_item,
            reversal_of=original,
            movement_type="return_to_stock",
            quantity=original.quantity,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            StockMovement.objects.create(
                company=self.company,
                product=self.product,
                stock_entry=self.entry,
                sale_item=self.sale_item,
                reversal_of=original,
                movement_type="return_to_stock",
                quantity=original.quantity,
            )

    def test_referenced_entry_cannot_be_deleted(self):
        self.create_sale_movement()

        with self.assertRaises(ProtectedError):
            self.entry.delete()
