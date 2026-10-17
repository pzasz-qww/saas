from copy import deepcopy

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import PrintJob, PrintSettings
from .snapshots import build_snapshot


def enqueue_order(*, order_id, company_id, using="default"):
    from orders.models import Order

    event_key = f"order:{order_id}:sold"
    existing = PrintJob.objects.using(using).filter(company_id=company_id, event_key=event_key).first()
    if existing:
        return existing
    settings = PrintSettings.objects.using(using).select_related("default_printer", "company").filter(company_id=company_id, automatic=True).first()
    if not settings or not settings.company.active or not settings.default_printer or not settings.default_printer.active:
        return None
    if settings.default_printer.company_id != company_id:
        raise ValidationError("Configuração de impressão de outra empresa.")
    order = Order.objects.using(using).select_related("sale", "company").get(pk=order_id, company_id=company_id)
    payload = build_snapshot(order, timezone_name=settings.timezone_name, using=using)
    job, _created = PrintJob.objects.using(using).get_or_create(
        company_id=company_id, event_key=event_key,
        defaults={"printer": settings.default_printer, "order_reference": order.pk, "payload": payload},
    )
    return job


def reprint_job(*, job_id, company_id):
    with transaction.atomic():
        original = PrintJob.objects.select_for_update().get(pk=job_id, company_id=company_id)
        if original.status not in {PrintJob.Status.PRINTED, PrintJob.Status.ERROR}:
            raise ValidationError("Aguarde o trabalho terminar ou registre o resultado incerto como erro antes de reimprimir.")
        if not original.printer.active:
            raise ValidationError("Ative a impressora antes de reimprimir.")
        return PrintJob.objects.create(
            company_id=company_id, printer=original.printer,
            order_reference=original.order_reference,
            payload=deepcopy(original.payload), reprint_of=original,
        )
