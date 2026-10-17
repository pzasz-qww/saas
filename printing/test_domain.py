from copy import deepcopy
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from accounts.models import Profile
from orders.models import Order, OrderItem
from orders.tests.helpers import make_company, make_order
from products.models import Product, StockEntry, StockMovement
from sales.models import Sale

from .models import BridgeCredential, PrintJob, Printer, PrintSettings
from .services import enqueue_order, reprint_job
from .snapshots import build_snapshot
from .test_helpers import PrintingCase


class SnapshotTests(PrintingCase):
    def test_snapshot_contains_persisted_values_and_original_time(self):
        order = self.sold_order()
        snapshot = build_snapshot(order)
        self.assertEqual(snapshot["total"], "20.00")
        self.assertEqual(snapshot["items"][0]["line_total"], "20.00")
        self.assertEqual(snapshot["items"][0]["observation"], "Bem gelada")
        self.assertEqual(snapshot["observation"], "Entregar na mesa")
        self.assertEqual(snapshot["payment_method"], "PIX")
        self.assertEqual(snapshot["table"], "7")
        self.assertEqual(snapshot["employee_role"], "Garçom")
        from datetime import datetime
        self.assertEqual(datetime.fromisoformat(snapshot["ordered_at"]), order.created_at)

    def test_reprint_preserves_snapshot_despite_source_changes_and_does_not_touch_business(self):
        job = self.job()
        expected = deepcopy(job.payload)
        Product.objects.filter(pk=self.product.pk).update(name="Outro nome", sale_price=Decimal("55"))
        Profile.objects.filter(user=self.user).update(role="manager")
        self.user.first_name = "Nome novo"
        self.user.save()
        before = [list(m.objects.values()) for m in (Order, OrderItem, Sale, StockEntry, StockMovement)]
        PrintJob.objects.filter(pk=job.pk).update(status="printed")
        reprint = reprint_job(job_id=job.pk, company_id=self.company.pk)
        after = [list(m.objects.values()) for m in (Order, OrderItem, Sale, StockEntry, StockMovement)]
        self.assertEqual(before, after)
        self.assertEqual(reprint.payload, expected)
        self.assertEqual(reprint.reprint_of_id, job.pk)
        self.assertEqual(PrintJob.objects.count(), 2)

    def test_same_event_is_idempotent(self):
        job = self.job()
        again = enqueue_order(order_id=job.order_reference, company_id=self.company.pk)
        self.assertEqual(job.pk, again.pk)
        self.assertEqual(PrintJob.objects.count(), 1)

    def test_snapshot_cannot_be_changed_by_save_update_or_bulk_update(self):
        job = self.job()
        job.payload["total"] = "999.00"
        with self.assertRaises(ValidationError):
            job.save()
        with self.assertRaises(ValidationError):
            PrintJob.objects.filter(pk=job.pk).update(payload=job.payload)
        with self.assertRaises(ValidationError):
            PrintJob.objects.bulk_update([job], ["payload"])
        with self.assertRaises(ValidationError):
            PrintJob.objects.filter(pk=job.pk).update(company=self.company)
        with self.assertRaises(ValidationError):
            PrintJob.objects.bulk_create([job], update_conflicts=True, update_fields=["payload"], unique_fields=["id"])

    def test_snapshot_uses_applied_prices_even_when_catalog_price_changes_before_job(self):
        order = self.sold_order()
        Product.objects.filter(pk=self.product.pk).update(sale_price=Decimal("55"))
        payload = build_snapshot(order)
        self.assertEqual(payload["items"][0]["unit_price"], "10.00")
        self.assertEqual(payload["items"][0]["line_total"], "20.00")
        self.assertEqual(payload["total"], "20.00")

    def test_pre_sale_cannot_be_enqueued(self):
        order, _ = make_order(company=self.company, lines=[(self.product, "1")])
        with self.assertRaises(ValidationError):
            enqueue_order(order_id=order.pk, company_id=self.company.pk)
        self.assertFalse(PrintJob.objects.exists())

    def test_legacy_data_is_explicitly_marked_missing(self):
        order = self.sold_order()
        from .models import ItemPrintContext, OrderPrintContext
        OrderPrintContext.objects.all().delete()
        ItemPrintContext.objects.all().delete()
        payload = build_snapshot(order)
        self.assertEqual(payload["employee_role"], "Cargo não registrado")
        self.assertEqual(payload["items"][0]["name_source"], "snapshot_creation")
        self.assertEqual(len(payload["missing_historical_data"]), 2)

    def test_invalid_sale_totals_are_rejected(self):
        order = self.sold_order()
        Sale.objects.filter(pk=order.sale_id).update(total_amount=Decimal("999"))
        order.refresh_from_db()
        with self.assertRaises(ValidationError):
            build_snapshot(order)

    def test_disabled_automatic_does_not_enqueue(self):
        order = self.sold_order()
        self.settings.automatic = False
        self.settings.save()
        self.assertIsNone(enqueue_order(order_id=order.pk, company_id=self.company.pk))

    def test_pending_job_cannot_be_reprinted(self):
        job = self.job()
        with self.assertRaises(ValidationError):
            reprint_job(job_id=job.pk, company_id=self.company.pk)

    def test_cross_company_relations_are_rejected(self):
        other = make_company()
        with self.assertRaises(ValidationError):
            PrintSettings.objects.create(company=other, default_printer=self.printer)
        with self.assertRaises(ValidationError):
            BridgeCredential.objects.create(company=other, printer=self.printer, secret_hash="hash")
        with self.assertRaises(ValidationError):
            PrintJob.objects.create(company=other, printer=self.printer, order_reference=1, payload={})
        job = self.job()
        with self.assertRaises(PrintJob.DoesNotExist):
            reprint_job(job_id=job.pk, company_id=other.pk)

    def test_event_unique_constraint_and_company_required(self):
        job = self.job()
        with self.assertRaises(IntegrityError), transaction.atomic():
            PrintJob.objects.create(company=self.company, printer=self.printer, order_reference=job.order_reference, payload=job.payload, event_key=job.event_key)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Printer.objects.create(name="Sem empresa")
