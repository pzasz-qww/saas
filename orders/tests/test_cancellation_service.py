from decimal import Decimal

from django.test import TestCase

from orders.models import Order
from orders.services import (
    approve_order,
    cancel_paid_order_with_stock_return,
)
from products.models import StockMovement
from products.services import UntraceableSaleStock
from sales.models import Sale

from .helpers import OrderTestMixin, fifo_times, make_company, make_entry


D = Decimal


class CancellationServiceTests(OrderTestMixin, TestCase):
    def make_approved_fifo_sale(self):
        product = self.make_product(sale_price="10.00")
        older_time, newer_time = fifo_times()
        older = make_entry(
            product=product,
            quantity="2.00",
            total_cost="4.00",
            created_at=older_time,
        )
        newer = make_entry(
            product=product,
            quantity="8.00",
            total_cost="32.00",
            created_at=newer_time,
        )
        order, _items = self.make_order([(product, "5.00", "10.00")])
        approval = approve_order(
            order_id=order.pk,
            company=self.company,
            payment_method="pix",
            user=self.user,
        )
        older.refresh_from_db()
        newer.refresh_from_db()
        order.refresh_from_db()
        return order, approval.sale, older, newer

    def test_cancellation_restores_original_entries_and_links_reversals(self):
        order, sale, older, newer = self.make_approved_fifo_sale()
        original_entry_count = older.product.stock_entries.count()
        outbound = list(
            StockMovement.objects.filter(movement_type="sale").order_by("id")
        )

        result = cancel_paid_order_with_stock_return(
            order_id=order.pk,
            company=self.company,
            user=self.user,
        )

        order.refresh_from_db()
        sale.refresh_from_db()
        older.refresh_from_db()
        newer.refresh_from_db()
        returns = list(
            StockMovement.objects.filter(
                movement_type="return_to_stock"
            ).select_related("reversal_of")
        )
        return_by_original = {
            movement.reversal_of_id: movement for movement in returns
        }

        self.assertTrue(result.restored)
        self.assertEqual(order.status, "cancelled")
        self.assertEqual(sale.status, "cancelled")
        self.assertEqual(older.remaining_quantity, D("2.00"))
        self.assertEqual(newer.remaining_quantity, D("8.00"))
        self.assertEqual(older.product.stock_entries.count(), original_entry_count)
        self.assertEqual(len(outbound), 2)
        self.assertEqual(len(returns), 2)
        self.assertEqual(
            sum((movement.quantity for movement in returns), D("0.00")),
            D("5.00"),
        )
        for original in outbound:
            reversal = return_by_original[original.pk]
            self.assertEqual(reversal.company_id, original.company_id)
            self.assertEqual(reversal.product_id, original.product_id)
            self.assertEqual(reversal.stock_entry_id, original.stock_entry_id)
            self.assertEqual(reversal.sale_item_id, original.sale_item_id)
            self.assertEqual(reversal.quantity, original.quantity)
            self.assertEqual(reversal.sale_value, D("0.00"))

    def test_duplicate_cancellation_from_stale_instances_restores_once(self):
        order, sale, older, newer = self.make_approved_fifo_sale()
        stale_first = Order.objects.get(pk=order.pk)
        stale_second = Order.objects.get(pk=order.pk)

        first_restored = stale_first.cancel_paid_and_return_stock(user=self.user)
        second_restored = stale_second.cancel_paid_and_return_stock(user=self.user)

        sale.refresh_from_db()
        older.refresh_from_db()
        newer.refresh_from_db()
        self.assertTrue(first_restored)
        self.assertFalse(second_restored)
        self.assertEqual(sale.status, "cancelled")
        self.assertEqual(older.remaining_quantity, D("2.00"))
        self.assertEqual(newer.remaining_quantity, D("8.00"))
        self.assertEqual(
            StockMovement.objects.filter(
                movement_type="return_to_stock"
            ).count(),
            2,
        )

    def test_legacy_sale_without_movement_origin_is_not_restored(self):
        order, sale, older, newer = self.make_approved_fifo_sale()
        StockMovement.objects.filter(movement_type="sale").update(sale_item=None)

        with self.assertRaises(UntraceableSaleStock):
            cancel_paid_order_with_stock_return(
                order_id=order.pk,
                company=self.company,
                user=self.user,
            )

        order.refresh_from_db()
        sale.refresh_from_db()
        older.refresh_from_db()
        newer.refresh_from_db()
        self.assertEqual(order.status, "sold")
        self.assertEqual(sale.status, "active")
        self.assertEqual(older.remaining_quantity, D("0.00"))
        self.assertEqual(newer.remaining_quantity, D("5.00"))
        self.assertFalse(
            StockMovement.objects.filter(
                movement_type="return_to_stock"
            ).exists()
        )

    def test_order_cannot_be_cancelled_through_another_company_context(self):
        order, sale, older, newer = self.make_approved_fifo_sale()
        other_company = make_company(name="Outra empresa")

        with self.assertRaises(Order.DoesNotExist):
            cancel_paid_order_with_stock_return(
                order_id=order.pk,
                company=other_company,
                user=self.user,
            )

        order.refresh_from_db()
        sale.refresh_from_db()
        older.refresh_from_db()
        newer.refresh_from_db()
        self.assertEqual(order.status, "sold")
        self.assertEqual(sale.status, "active")
        self.assertEqual(older.remaining_quantity, D("0.00"))
        self.assertEqual(newer.remaining_quantity, D("5.00"))
        self.assertEqual(
            StockMovement.objects.filter(
                movement_type="return_to_stock"
            ).count(),
            0,
        )
