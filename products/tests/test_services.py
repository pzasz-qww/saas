from decimal import Decimal

from django.test import TestCase

from companies.models import Company
from products.models import Product, StockEntry, StockMovement, Unit
from products.services import apply_negative_adjustment, apply_positive_adjustment


class StockAdjustmentServiceTests(TestCase):
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

    def make_entry(self, quantity, total_cost):
        return StockEntry.objects.create(
            company=self.company,
            product=self.product,
            total_cost=Decimal(total_cost),
            quantity_added=Decimal(quantity),
        )

    def test_stock_movement_save_has_no_hidden_stock_effect(self):
        entry = self.make_entry("10.00", "50.00")

        StockMovement.objects.create(
            company=self.company,
            product=self.product,
            stock_entry=entry,
            movement_type="adjustment_negative",
            quantity=Decimal("3.00"),
        )

        entry.refresh_from_db()
        self.assertEqual(entry.remaining_quantity, Decimal("10.00"))

    def test_positive_adjustment_explicitly_creates_entry_and_movement(self):
        movement = apply_positive_adjustment(
            company=self.company,
            product=self.product,
            quantity=Decimal("3.00"),
            cost_value=Decimal("6.00"),
        )

        self.assertEqual(self.product.current_stock, Decimal("3.00"))
        self.assertEqual(movement.quantity, Decimal("3.00"))
        self.assertIsNotNone(movement.stock_entry_id)
        self.assertEqual(movement.stock_entry.remaining_quantity, Decimal("3.00"))

    def test_negative_adjustment_consumes_multiple_entries_fifo(self):
        first = self.make_entry("2.00", "4.00")
        second = self.make_entry("8.00", "24.00")

        movements = apply_negative_adjustment(
            company=self.company,
            product=self.product,
            quantity=Decimal("5.00"),
        )

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.remaining_quantity, Decimal("0.00"))
        self.assertEqual(second.remaining_quantity, Decimal("5.00"))
        self.assertEqual(len(movements), 2)
        self.assertEqual(
            sum((movement.quantity for movement in movements), Decimal("0.00")),
            Decimal("5.00"),
        )
