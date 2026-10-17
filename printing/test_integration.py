from unittest.mock import patch

from django.db import DatabaseError, transaction

from accounts.models import Profile, StaffRole
from orders.models import Order
from orders.services import approve_order
from orders.tests.helpers import make_order
from products.models import StockMovement
from sales.models import Sale

from .models import ItemPrintContext, OrderPrintContext, PrintJob
from .test_helpers import PrintingCase


class IntegrationTests(PrintingCase):
    def draft(self):
        with self.captureOnCommitCallbacks(execute=True):
            order, items = make_order(company=self.company, created_by=self.user, lines=[(self.product, "2")])
        return order, items

    def test_pre_sale_creates_context_but_no_job(self):
        order, items = self.draft()
        self.assertFalse(PrintJob.objects.exists())
        self.assertEqual(OrderPrintContext.objects.get(order_reference=order.pk).employee_role, "Garçom")
        self.assertEqual(ItemPrintContext.objects.get(item_reference=items[0].pk).product_name, "Heineken")

    def test_job_only_after_commit_and_uses_complete_sale(self):
        order, items = self.draft()
        with self.captureOnCommitCallbacks(execute=True):
            approve_order(order_id=order.pk, company=self.company, payment_method="pix", user=self.user)
            self.assertFalse(PrintJob.objects.exists())
        job = PrintJob.objects.get()
        self.assertEqual(job.payload["items"][0]["line_total"], "20.00")
        self.assertEqual(job.payload["total"], "20.00")
        self.assertEqual(job.payload["payment_method"], "PIX")
        self.assertEqual(job.event_key, f"order:{order.pk}:sold")

    def test_original_role_name_and_product_name_survive_changes_before_approval(self):
        role = StaffRole.objects.create(company=self.company, name="Garçom salão")
        Profile.objects.filter(user=self.user).update(role_template=role)
        order, _ = self.draft()
        role.name = "Gerência"
        role.save()
        self.product.name = "Produto renomeado"
        self.product.save()
        self.user.first_name = "Novo nome"
        self.user.save()
        with self.captureOnCommitCallbacks(execute=True):
            approve_order(order_id=order.pk, company=self.company, payment_method="cash", user=self.user)
        payload = PrintJob.objects.get().payload
        self.assertEqual(payload["employee_role"], "Garçom salão")
        self.assertEqual(payload["employee_name"], "Pedro")
        self.assertEqual(payload["items"][0]["name"], "Heineken")

    def test_rollback_discards_callbacks_and_jobs(self):
        order, _ = self.draft()
        with self.captureOnCommitCallbacks(execute=True):
            with self.assertRaises(RuntimeError), transaction.atomic():
                approve_order(order_id=order.pk, company=self.company, payment_method="pix", user=self.user)
                raise RuntimeError("rollback")
        self.assertFalse(PrintJob.objects.exists())
        self.assertFalse(Sale.objects.exists())
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.remaining_quantity, 20)

    def test_enqueue_failure_does_not_rollback_sale_stock_or_order(self):
        order, _ = self.draft()
        with patch("printing.signals.enqueue_order", side_effect=DatabaseError("printing unavailable")):
            with self.assertLogs("printing.signals", level="ERROR"):
                with self.captureOnCommitCallbacks(execute=True):
                    approve_order(order_id=order.pk, company=self.company, payment_method="pix", user=self.user)
        order.refresh_from_db()
        self.entry.refresh_from_db()
        self.assertEqual(order.status, "sold")
        self.assertEqual(order.sale.payment_method, "pix")
        self.assertEqual(self.entry.remaining_quantity, 18)
        self.assertEqual(StockMovement.objects.filter(movement_type="sale").count(), 1)

    def test_duplicate_sale_signals_create_one_job(self):
        order, _ = self.draft()
        with self.captureOnCommitCallbacks(execute=True):
            sale = approve_order(order_id=order.pk, company=self.company, payment_method="pix", user=self.user).sale
            sale.save()
            sale.save()
        self.assertEqual(PrintJob.objects.count(), 1)

    def test_context_failure_never_blocks_order_creation(self):
        with patch("printing.signals.persist_context", side_effect=DatabaseError("printing unavailable")):
            with self.assertLogs("printing.signals", level="ERROR"):
                order, items = self.draft()
        self.assertTrue(Order.objects.filter(pk=order.pk).exists())
        self.assertEqual(order.items.count(), 1)

    def test_cancelled_sale_before_commit_does_not_enqueue(self):
        order, _ = self.draft()
        with self.captureOnCommitCallbacks(execute=True):
            sale = approve_order(order_id=order.pk, company=self.company, payment_method="pix", user=self.user).sale
            Sale.objects.filter(pk=sale.pk).update(status="cancelled")
        self.assertFalse(PrintJob.objects.exists())
