"""Queue transitions only. These services never write to business tables."""
import secrets
import uuid

from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.models import F
from django.utils import timezone

from .models import BridgeCredential, PrintJob


def issue_credential(printer):
    secret = secrets.token_urlsafe(32)
    credential = BridgeCredential.objects.create(company_id=printer.company_id, printer=printer, secret_hash=make_password(secret))
    return credential, f"{credential.identifier}.{secret}"


def authenticate(token):
    if not isinstance(token, str) or len(token) > 200:
        return None
    try:
        identifier, secret = token.split(".", 1)
        identifier = uuid.UUID(identifier)
    except (ValueError, AttributeError):
        return None
    credential = BridgeCredential.objects.select_related("company", "printer").filter(identifier=identifier, active=True, company__active=True).first()
    if not credential or credential.printer.company_id != credential.company_id:
        return None
    return credential if check_password(secret, credential.secret_hash) else None


def claim_next(credential):
    if not credential.printer.active:
        return None
    with transaction.atomic():
        jobs = PrintJob.objects.filter(company_id=credential.company_id, printer_id=credential.printer_id, printer__company_id=credential.company_id, status=PrintJob.Status.PENDING).order_by("pk")
        if connection.features.has_select_for_update:
            jobs = jobs.select_for_update(skip_locked=connection.features.has_select_for_update_skip_locked, of=("self",))
        job = jobs.first()
        if job is None:
            return None
        token = uuid.uuid4()
        changed = PrintJob.objects.filter(pk=job.pk, status=PrintJob.Status.PENDING).update(
            status=PrintJob.Status.PROCESSING, claimed_by=credential, claim_token=token,
            claimed_at=timezone.now(), attempts=F("attempts") + 1, last_error="",
        )
        if changed != 1:
            return None
        job.refresh_from_db()
        return job


def finish_job(*, credential, job_id, claim_token, success, error=""):
    try:
        claim_token = uuid.UUID(str(claim_token))
    except ValueError:
        raise ValidationError("Claim inválido.") from None
    target = PrintJob.Status.PRINTED if success else PrintJob.Status.ERROR
    scope = PrintJob.objects.filter(pk=job_id, company_id=credential.company_id, printer_id=credential.printer_id, claimed_by=credential, claim_token=claim_token)
    updates = {"status": target, "printed_at": timezone.now() if success else None, "last_error": "" if success else str(error)[:2000]}
    if scope.filter(status=PrintJob.Status.PROCESSING).update(**updates):
        return scope.get()
    job = scope.get()
    if job.status != target:
        raise ValidationError("Trabalho já finalizado com outro resultado.")
    return job  # Acknowledgements are safe to retry after a lost HTTP response.


def mark_uncertain(*, job_id, company_id):
    return PrintJob.objects.filter(pk=job_id, company_id=company_id, status=PrintJob.Status.PROCESSING).update(
        status=PrintJob.Status.ERROR,
        last_error="Resultado físico incerto. Operador encerrou o claim; conferir papel antes de reimprimir.",
    )
