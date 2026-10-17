"""Recreate review artifacts in a temporary database, never the operational DB.

Run: python -m printing.examples.generate
"""
from datetime import datetime
from decimal import Decimal
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory


def main():
    with TemporaryDirectory(prefix="printing-example-") as directory:
        os.environ["DATABASE_URL"] = "sqlite:///" + (Path(directory) / "example.sqlite3").as_posix()
        os.environ["DEPLOYMENT_MODE"] = "development"
        os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"
        import django
        django.setup()
        from django.conf import settings
        from django.core.management import call_command
        from django.db import connections
        from django.test import Client
        from orders.models import Order, OrderItem
        from orders.services import approve_order
        from orders.tests.helpers import make_company, make_entry, make_product, make_user
        from printing.models import Printer, PrintJob, PrintSettings
        from print_bridge.renderer import render_html, render_text

        settings.ALLOWED_HOSTS = ["testserver"]
        call_command("migrate", verbosity=0)
        company = make_company(name="BAR PRAÇA KENNEDY")
        user = make_user(company=company, role="waiter", username="pedro")
        user.first_name = "Pedro"
        user.save()
        owner = make_user(company=company, role="owner", username="dono_demo")
        printer = Printer.objects.create(company=company, name="Balcão · 80 mm")
        PrintSettings.objects.create(company=company, default_printer=printer, automatic=True)
        order = Order.objects.create(pk=184, company=company, created_by=user, table_or_tab="7")
        Order.objects.filter(pk=order.pk).update(created_at=datetime.fromisoformat("2026-08-27T21:42:00-03:00"))
        for name, price, qty, notes in [("Heineken", "10.00", "2", ""), ("Calabresa", "45.00", "1", "sem cebola")]:
            product = make_product(company=company, name=name, sale_price=price)
            make_entry(product=product, quantity="20")
            OrderItem.objects.create(order=order, company=company, product=product, quantity=Decimal(qty), notes=notes)
        approve_order(order_id=order.pk, company=company, payment_method="pix", user=owner)
        job = PrintJob.objects.get()
        root = Path(__file__).parent
        (root / "ticket.json").write_text(json.dumps(job.payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (root / "ticket.txt").write_text(render_text(job.payload), encoding="utf-8")
        (root / "ticket.html").write_text('<!doctype html><html lang="pt-br"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Ticket Prebeta 4</title><body style="background:#f1f3f5;padding:24px"><main style="background:white;width:max-content;padding:24px;margin:auto">' + render_html(job.payload) + '</main></body></html>', encoding="utf-8")
        client = Client()
        client.force_login(owner)
        for name, url in [("settings", "/printing/settings/"), ("jobs", "/printing/jobs/"), ("preview", f"/printing/jobs/{job.pk}/preview/")]:
            response = client.get(url)
            if response.status_code != 200:
                raise RuntimeError(f"Preview {name}: HTTP {response.status_code}")
            # Review-only pages; no operational session or credential is exported.
            import re
            html = response.content.decode("utf-8")
            html = re.sub(r'<input[^>]+name="csrfmiddlewaretoken"[^>]*>', '', html)
            project = root.parent.parent
            html = re.sub(r'<link rel="stylesheet" href="/static/([^\"]+)">', lambda match: '<style>' + (project / 'static' / match.group(1)).read_text(encoding='utf-8') + '</style>', html)
            html = re.sub(r'<script src="/static/[^\"]+"></script>', '', html)
            (root / f"ui-{name}.html").write_text(html, encoding="utf-8")
        connections.close_all()
        print("Snapshot and previews saved in printing/examples from an isolated database.")


if __name__ == "__main__":
    main()
