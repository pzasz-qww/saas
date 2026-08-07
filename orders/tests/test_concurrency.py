from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connections
from django.test import TransactionTestCase, skipUnlessDBFeature

from companies.models import Company
from orders.models import OrderItem
from orders.services import (
    approve_order,
    cancel_paid_order_with_stock_return,
    mark_order_delivered,
)
from products.models import StockEntry, StockMovement
from products.services import InsufficientStock
from sales.models import Sale, SaleItem

from .helpers import OrderTestMixin, make_entry


@skipUnlessDBFeature("has_select_for_update")
class ApprovalConcurrencyTests(OrderTestMixin, TransactionTestCase):
    """Real lock tests.

    SQLite deliberately skips this class because it ignores SELECT ... FOR UPDATE
    and commonly returns database-lock errors for threaded writes. The sequential
    idempotency and rollback tests still run on every supported backend. Run this
    class against PostgreSQL to validate row-lock behavior.
    """

    reset_sequences = True

    def _run_concurrently(self, order_ids):
        barrier = Barrier(len(order_ids))
        company_id = self.company.pk
        user_id = self.user.pk

        def worker(order_id):
            close_old_connections()
            try:
                company = Company.objects.get(pk=company_id)
                user = get_user_model().objects.get(pk=user_id)
                barrier.wait(timeout=10)
                try:
                    result = approve_order(
                        order_id=order_id,
                        company=company,
                        payment_method="pix",
                        user=user,
                    )
                except InsufficientStock:
                    return "insufficient", None
                return "approved", result.created
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(order_ids)) as executor:
            futures = [executor.submit(worker, order_id) for order_id in order_ids]
            return [future.result(timeout=20) for future in futures]

    def test_two_concurrent_attempts_approve_same_order_once(self):
        product = self.make_product()
        entry = make_entry(product=product, quantity="10.00")
        order, _items = self.make_order([(product, "3.00", "10.00")])

        results = self._run_concurrently([order.pk, order.pk])

        entry.refresh_from_db()
        order.refresh_from_db()
        self.assertCountEqual(results, [("approved", True), ("approved", False)])
        self.assertEqual(order.status, "sold")
        self.assertEqual(entry.remaining_quantity, entry.quantity_added - 3)
        self.assertEqual(Sale.objects.count(), 1)
        self.assertEqual(SaleItem.objects.count(), 1)
        self.assertEqual(
            StockMovement.objects.filter(movement_type="sale").count(),
            1,
        )

    def test_two_orders_competing_for_same_entry_cannot_oversell(self):
        product = self.make_product()
        entry = make_entry(product=product, quantity="5.00")
        first_order, _items = self.make_order([(product, "4.00", "10.00")])
        second_order, _items = self.make_order([(product, "4.00", "10.00")])

        results = self._run_concurrently([first_order.pk, second_order.pk])

        entry.refresh_from_db()
        statuses = list(
            type(first_order).objects.filter(
                pk__in=[first_order.pk, second_order.pk]
            ).values_list("status", flat=True)
        )
        self.assertCountEqual(
            results,
            [("approved", True), ("insufficient", None)],
        )
        self.assertCountEqual(statuses, ["sold", "pre_sale"])
        self.assertEqual(entry.remaining_quantity, entry.quantity_added - 4)
        self.assertEqual(Sale.objects.count(), 1)
        self.assertEqual(SaleItem.objects.count(), 1)
        self.assertEqual(
            StockMovement.objects.filter(movement_type="sale").count(),
            1,
        )


@skipUnlessDBFeature("has_select_for_update")
class OrderStateConcurrencyTests(OrderTestMixin, TransactionTestCase):
    """PostgreSQL coverage for state and item locks on the Order row."""

    reset_sequences = True

    def test_item_edit_waits_for_approval_and_is_then_rejected(self):
        product = self.make_product()
        entry = make_entry(product=product, quantity="10.00")
        order, items = self.make_order([(product, "2.00", "10.00")])
        item = items[0]
        approval_has_order_lock = Event()
        release_approval = Event()
        edit_started = Event()
        original_consume_stock = __import__(
            "orders.services",
            fromlist=["consume_stock"],
        ).consume_stock
        company_id = self.company.pk
        user_id = self.user.pk

        def blocking_consume_stock(*args, **kwargs):
            approval_has_order_lock.set()
            if not release_approval.wait(timeout=10):
                raise AssertionError("Timed out waiting to release approval")
            return original_consume_stock(*args, **kwargs)

        def approval_worker():
            close_old_connections()
            try:
                return approve_order(
                    order_id=order.pk,
                    company=Company.objects.get(pk=company_id),
                    payment_method="pix",
                    user=get_user_model().objects.get(pk=user_id),
                ).created
            finally:
                connections.close_all()

        def edit_worker():
            close_old_connections()
            try:
                editable = OrderItem.objects.get(pk=item.pk)
                editable.quantity = 9
                edit_started.set()
                try:
                    editable.save()
                except ValidationError:
                    return "rejected"
                return "saved"
            finally:
                connections.close_all()

        with patch(
            "orders.services.consume_stock",
            side_effect=blocking_consume_stock,
        ):
            with ThreadPoolExecutor(max_workers=2) as executor:
                approval_future = executor.submit(approval_worker)
                self.assertTrue(approval_has_order_lock.wait(timeout=10))
                edit_future = executor.submit(edit_worker)
                self.assertTrue(edit_started.wait(timeout=10))
                release_approval.set()
                approval_created = approval_future.result(timeout=20)
                edit_result = edit_future.result(timeout=20)

        order.refresh_from_db()
        item.refresh_from_db()
        entry.refresh_from_db()
        self.assertTrue(approval_created)
        self.assertEqual(edit_result, "rejected")
        self.assertEqual(order.status, "sold")
        self.assertEqual(item.quantity, 2)
        self.assertEqual(entry.remaining_quantity, 8)

    def test_delivery_and_paid_cancellation_serialize_consistently(self):
        product = self.make_product()
        entry = make_entry(product=product, quantity="5.00")
        order, _items = self.make_order([(product, "2.00", "10.00")])
        approval = approve_order(
            order_id=order.pk,
            company=self.company,
            payment_method="pix",
            user=self.user,
        )
        barrier = Barrier(2)
        company_id = self.company.pk
        user_id = self.user.pk

        def deliver_worker():
            close_old_connections()
            try:
                company = Company.objects.get(pk=company_id)
                barrier.wait(timeout=10)
                return mark_order_delivered(
                    order_id=order.pk,
                    company=company,
                ).changed
            finally:
                connections.close_all()

        def cancel_worker():
            close_old_connections()
            try:
                company = Company.objects.get(pk=company_id)
                user = get_user_model().objects.get(pk=user_id)
                barrier.wait(timeout=10)
                return cancel_paid_order_with_stock_return(
                    order_id=order.pk,
                    company=company,
                    user=user,
                ).restored
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            delivered_future = executor.submit(deliver_worker)
            cancelled_future = executor.submit(cancel_worker)
            delivered_future.result(timeout=20)
            restored = cancelled_future.result(timeout=20)

        order.refresh_from_db()
        approval.sale.refresh_from_db()
        entry.refresh_from_db()
        self.assertTrue(restored)
        self.assertEqual(order.status, "cancelled")
        self.assertEqual(approval.sale.status, "cancelled")
        self.assertEqual(entry.remaining_quantity, entry.quantity_added)
        self.assertEqual(
            StockMovement.objects.filter(
                movement_type="return_to_stock"
            ).count(),
            1,
        )
