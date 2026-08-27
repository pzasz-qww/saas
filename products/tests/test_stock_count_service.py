from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from companies.models import Company
from products.models import Product, StockEntry, StockMovement, Unit
from products.services import (
    InvalidStockOperation,
    StockConcurrencyError,
    apply_stock_count,
)


class StockCountServiceTests(TestCase):
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

    def test_count_without_difference_records_only_the_count(self):
        entry = self.make_entry("10.00", "50.00")

        result = apply_stock_count(
            company=self.company,
            product=self.product,
            real_quantity=Decimal("10.00"),
            notes="Fechamento",
        )

        entry.refresh_from_db()
        self.assertEqual(entry.remaining_quantity, Decimal("10.00"))
        self.assertEqual(result.expected_quantity, Decimal("10.00"))
        self.assertEqual(result.real_quantity, Decimal("10.00"))
        self.assertEqual(result.difference, Decimal("0.00"))
        self.assertEqual(result.adjustment_movements, ())
        self.assertEqual(result.stock_count_movement.movement_type, "stock_count")
        self.assertEqual(result.stock_count_movement.quantity, Decimal("10.00"))
        self.assertEqual(result.stock_count_movement.cost_value, Decimal("50.00"))
        self.assertIn("Fechamento", result.stock_count_movement.notes)
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_positive_difference_creates_one_entry_and_adjustment(self):
        original_entry = self.make_entry("10.00", "50.00")

        result = apply_stock_count(
            company=self.company,
            product=self.product,
            real_quantity=Decimal("13.00"),
        )

        original_entry.refresh_from_db()
        self.assertEqual(original_entry.remaining_quantity, Decimal("10.00"))
        self.assertEqual(result.expected_quantity, Decimal("10.00"))
        self.assertEqual(result.difference, Decimal("3.00"))
        self.assertEqual(len(result.adjustment_movements), 1)

        adjustment = result.adjustment_movements[0]
        adjustment.stock_entry.refresh_from_db()
        self.assertEqual(adjustment.movement_type, "adjustment_positive")
        self.assertEqual(adjustment.quantity, Decimal("3.00"))
        self.assertEqual(adjustment.cost_value, Decimal("15.00"))
        self.assertEqual(
            adjustment.stock_entry.remaining_quantity,
            Decimal("3.00"),
        )
        self.assertEqual(self.product.current_stock, Decimal("13.00"))
        self.assertEqual(StockMovement.objects.count(), 2)

    def test_negative_difference_consumes_entries_in_fifo_order(self):
        first_entry = self.make_entry("2.00", "4.00")
        second_entry = self.make_entry("8.00", "24.00")

        result = apply_stock_count(
            company=self.company,
            product=self.product,
            real_quantity=Decimal("5.00"),
        )

        first_entry.refresh_from_db()
        second_entry.refresh_from_db()
        self.assertEqual(first_entry.remaining_quantity, Decimal("0.00"))
        self.assertEqual(second_entry.remaining_quantity, Decimal("5.00"))
        self.assertEqual(result.expected_quantity, Decimal("10.00"))
        self.assertEqual(result.difference, Decimal("-5.00"))
        self.assertEqual(
            [movement.stock_entry_id for movement in result.adjustment_movements],
            [first_entry.pk, second_entry.pk],
        )
        self.assertEqual(
            [movement.quantity for movement in result.adjustment_movements],
            [Decimal("2.00"), Decimal("3.00")],
        )
        self.assertEqual(self.product.current_stock, Decimal("5.00"))
        self.assertEqual(StockMovement.objects.count(), 3)

    def test_adjustment_failure_rolls_back_count_and_stock_change(self):
        entry = self.make_entry("10.00", "50.00")
        original_save = StockMovement.save

        def fail_negative_adjustment(movement, *args, **kwargs):
            if movement.movement_type == "adjustment_negative":
                raise StockConcurrencyError("Falha injetada no ajuste.")
            return original_save(movement, *args, **kwargs)

        with patch.object(
            StockMovement,
            "save",
            new=fail_negative_adjustment,
        ):
            with self.assertRaises(StockConcurrencyError):
                apply_stock_count(
                    company=self.company,
                    product=self.product,
                    real_quantity=Decimal("5.00"),
                )

        entry.refresh_from_db()
        self.assertEqual(entry.remaining_quantity, Decimal("10.00"))
        self.assertEqual(StockEntry.objects.count(), 1)
        self.assertFalse(StockMovement.objects.exists())

    def test_count_rejects_product_from_another_company(self):
        other_company = Company.objects.create(name="Outra empresa")
        other_unit = Unit.objects.create(
            company=other_company,
            name="Unidade",
            symbol="un",
        )
        other_product = Product.objects.create(
            company=other_company,
            name="Outro produto",
            unit=other_unit,
            sale_price=Decimal("8.00"),
        )
        other_entry = StockEntry.objects.create(
            company=other_company,
            product=other_product,
            total_cost=Decimal("30.00"),
            quantity_added=Decimal("10.00"),
        )

        with self.assertRaises(InvalidStockOperation):
            apply_stock_count(
                company=self.company,
                product=other_product,
                real_quantity=Decimal("2.00"),
            )

        other_entry.refresh_from_db()
        self.assertEqual(other_entry.remaining_quantity, Decimal("10.00"))
        self.assertFalse(StockMovement.objects.exists())
