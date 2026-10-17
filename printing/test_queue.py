import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.db import close_old_connections, connections
from django.test import Client, TransactionTestCase, skipUnlessDBFeature
from django.urls import reverse

from orders.tests.helpers import make_company
from .models import BridgeCredential, PrintJob, Printer
from .queue import claim_next, finish_job, issue_credential
from .test_helpers import PrintingCase


class QueueTests(PrintingCase):
    def setUp(self):
        super().setUp()
        self.credential, self.token = issue_credential(self.printer)
        self.headers = {"HTTP_AUTHORIZATION": f"Bearer {self.token}"}

    def test_secret_is_hashed_and_employee_session_is_not_authentication(self):
        self.assertNotIn(self.token.split(".")[1], self.credential.secret_hash)
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(reverse("printing:bridge_claim")).status_code, 401)
        self.assertEqual(self.client.get(reverse("printing:bridge_claim"), **self.headers).status_code, 405)

    def test_claim_once_and_success_is_idempotent(self):
        job = self.job()
        first = self.client.post(reverse("printing:bridge_claim"), **self.headers).json()["job"]
        self.assertEqual(first["id"], job.pk)
        self.assertIsNone(self.client.post(reverse("printing:bridge_claim"), **self.headers).json()["job"])
        url = reverse("printing:bridge_result", args=[job.pk])
        data = {"claim_token": first["claim_token"], "status": "printed"}
        for _ in range(2):
            self.assertEqual(self.client.post(url, data=json.dumps(data), content_type="application/json", **self.headers).status_code, 200)
        job.refresh_from_db()
        self.assertEqual(job.status, "printed")
        self.assertEqual(job.attempts, 1)
        self.assertIsNotNone(job.printed_at)

    def test_other_company_and_other_credential_cannot_claim_or_ack(self):
        job = self.job()
        claimed = claim_next(self.credential)
        other = make_company()
        other_printer = Printer.objects.create(company=other, name="Outra")
        other_credential, other_token = issue_credential(other_printer)
        headers = {"HTTP_AUTHORIZATION": f"Bearer {other_token}"}
        self.assertIsNone(self.client.post(reverse("printing:bridge_claim"), **headers).json()["job"])
        response = self.client.post(reverse("printing:bridge_result", args=[job.pk]), data=json.dumps({"claim_token": str(claimed.claim_token), "status": "printed"}), content_type="application/json", **headers)
        self.assertEqual(response.status_code, 404)
        sibling, _ = issue_credential(self.printer)
        with self.assertRaises(PrintJob.DoesNotExist):
            finish_job(credential=sibling, job_id=job.pk, claim_token=claimed.claim_token, success=True)

    def test_error_keeps_sale_and_stock_intact_and_is_not_reclaimed(self):
        from orders.models import Order
        from products.models import StockEntry, StockMovement
        from sales.models import Sale
        job = self.job()
        before = [list(m.objects.values()) for m in (Order, Sale, StockEntry, StockMovement)]
        claimed = claim_next(self.credential)
        finish_job(credential=self.credential, job_id=job.pk, claim_token=claimed.claim_token, success=False, error="Rede indisponível")
        job.refresh_from_db()
        self.assertEqual(job.status, "error")
        self.assertEqual(job.last_error, "Rede indisponível")
        self.assertEqual(before, [list(m.objects.values()) for m in (Order, Sale, StockEntry, StockMovement)])
        self.assertIsNone(claim_next(self.credential))

    def test_revoked_credential_and_inactive_company_are_denied(self):
        BridgeCredential.objects.filter(pk=self.credential.pk).update(active=False)
        self.assertEqual(self.client.post(reverse("printing:bridge_claim"), **self.headers).status_code, 401)
        BridgeCredential.objects.filter(pk=self.credential.pk).update(active=True)
        self.company.active = False
        self.company.save()
        self.assertEqual(self.client.post(reverse("printing:bridge_claim"), **self.headers).status_code, 401)

    def test_malformed_and_conflicting_results(self):
        job = self.job()
        claimed = claim_next(self.credential)
        url = reverse("printing:bridge_result", args=[job.pk])
        for data in ["not json", "[]", '{"status": "unknown"}', '{"status": "error", "error": []}']:
            self.assertEqual(self.client.post(url, data=data, content_type="application/json", **self.headers).status_code, 400)
        finish_job(credential=self.credential, job_id=job.pk, claim_token=claimed.claim_token, success=True)
        data = {"status": "error", "error": "late", "claim_token": str(claimed.claim_token)}
        self.assertEqual(self.client.post(url, data=json.dumps(data), content_type="application/json", **self.headers).status_code, 409)


@skipUnlessDBFeature("has_select_for_update")
class ClaimConcurrencyTests(TransactionTestCase):
    def test_two_consumers_obtain_one_job_only(self):
        company = make_company()
        printer = Printer.objects.create(company=company, name="TCP")
        first, _ = issue_credential(printer)
        second, _ = issue_credential(printer)
        job = PrintJob.objects.create(company=company, printer=printer, order_reference=184, payload={})
        barrier = Barrier(2)
        def worker(pk):
            close_old_connections()
            try:
                credential = BridgeCredential.objects.select_related("printer").get(pk=pk)
                barrier.wait(timeout=10)
                claimed = claim_next(credential)
                return claimed.pk if claimed else None
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker, pk) for pk in (first.pk, second.pk)]
            results = [f.result(timeout=20) for f in futures]
        self.assertCountEqual(results, [job.pk, None])
        job.refresh_from_db()
        self.assertEqual(job.attempts, 1)
