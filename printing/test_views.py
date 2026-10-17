from django.test import Client
from django.urls import reverse

from orders.tests.helpers import make_company, make_user
from .models import BridgeCredential, PrintJob, Printer
from .test_helpers import PrintingCase


class PrintingViewTests(PrintingCase):
    def setUp(self):
        super().setUp()
        self.owner = make_user(company=self.company)
        self.client.force_login(self.owner)

    def test_settings_uses_isolated_template_and_saves_printer(self):
        response = self.client.get(reverse("printing:settings"))
        self.assertTemplateUsed(response, "printing/prebeta4/settings.html")
        response = self.client.post(reverse("printing:settings"), {"action": "save_printer", "name": "Nova", "active": "on", "paper_width": 80, "characters_per_line": 42})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Printer.objects.filter(company=self.company, name="Nova").exists())

    def test_other_company_jobs_preview_reprint_and_printer_are_inaccessible(self):
        job = self.job()
        other = make_company()
        self.client.force_login(make_user(company=other))
        response = self.client.get(reverse("printing:jobs"))
        self.assertEqual(list(response.context["page"]), [])
        self.assertNotContains(response, reverse("printing:preview", args=[job.pk]))
        for route in ["preview", "reprint", "uncertain"]:
            method = self.client.get if route == "preview" else self.client.post
            self.assertEqual(method(reverse(f"printing:{route}", args=[job.pk])).status_code, 404)
        response = self.client.post(reverse("printing:settings"), {"action": "issue_token", "printer_id": self.printer.pk})
        self.assertEqual(response.status_code, 404)
        response = self.client.post(reverse("printing:settings"), {"action": "save_settings", "default_printer": self.printer.pk, "automatic": "on", "timezone_name": "America/Sao_Paulo"})
        self.assertEqual(response.context["settings_form"].errors.as_data()["default_printer"][0].code, "invalid_choice")

    def test_waiter_cannot_configure_view_queue_or_reprint(self):
        self.client.force_login(self.user)
        job = self.job()
        for url in [reverse("printing:settings"), reverse("printing:jobs"), reverse("printing:preview", args=[job.pk])]:
            self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(reverse("printing:reprint", args=[job.pk])).status_code, 403)

    def test_invalid_printer_edit_keeps_error_on_existing_printer(self):
        response = self.client.post(reverse("printing:settings"), {"action": "save_printer", "printer_id": self.printer.pk, "name": "Balcão", "paper_width": 80, "characters_per_line": 2})
        existing, form = response.context["printer_forms"][0]
        self.assertEqual(existing.pk, self.printer.pk)
        self.assertIn("characters_per_line", form.errors)
        self.assertIsNone(response.context["printer_form"].instance.pk)

    def test_preview_uses_escaped_snapshot(self):
        job = self.job()
        response = self.client.get(reverse("printing:preview", args=[job.pk]))
        self.assertContains(response, "HEINEKEN")
        self.assertContains(response, "Garçom: Pedro")
        self.assertContains(response, "R$ 20,00")

    def test_reprint_requires_post_and_csrf(self):
        job = self.job()
        self.assertEqual(self.client.get(reverse("printing:reprint", args=[job.pk])).status_code, 405)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        self.assertEqual(client.post(reverse("printing:reprint", args=[job.pk])).status_code, 403)

    def test_token_is_shown_once_and_rotation_revokes_previous(self):
        url = reverse("printing:settings")
        response = self.client.post(url, {"action": "issue_token", "printer_id": self.printer.pk})
        self.assertContains(response, "Credencial do bridge")
        self.assertEqual(response["Cache-Control"], "no-store")
        token = response.context["token"]
        self.assertTrue(token)
        self.assertNotContains(self.client.get(url), token)
        self.client.post(url, {"action": "issue_token", "printer_id": self.printer.pk})
        self.assertEqual(BridgeCredential.objects.filter(active=True).count(), 1)
        self.assertEqual(BridgeCredential.objects.filter(active=False).count(), 1)

    def test_status_and_error_list_and_uncertain_confirmation(self):
        job = self.job()
        PrintJob.objects.filter(pk=job.pk).update(status="processing")
        response = self.client.get(reverse("printing:jobs"))
        self.assertContains(response, "Imprimindo")
        self.client.post(reverse("printing:uncertain", args=[job.pk]))
        job.refresh_from_db()
        self.assertEqual(job.status, "processing")
        self.client.post(reverse("printing:uncertain", args=[job.pk]), {"confirmed": "yes"})
        job.refresh_from_db()
        self.assertEqual(job.status, "error")
        self.client.post(reverse("printing:reprint", args=[job.pk]))
        self.assertEqual(PrintJob.objects.count(), 2)
