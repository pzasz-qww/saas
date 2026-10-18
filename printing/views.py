from functools import wraps
import os
from pathlib import Path
from urllib.parse import urlsplit

from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_POST, require_http_methods

from accounts.permissions import company_required, has_permission
from print_bridge.renderer import render_html, render_text

from .forms import PrinterForm, PrintSettingsForm
from .models import BridgeCredential, PrintJob, Printer, PrintSettings
from .queue import issue_credential, mark_uncertain
from .services import reprint_job


def printer_for_company(queryset, value, company):
    try:
        pk = int(value)
    except (ValueError, TypeError):
        raise Http404 from None
    return get_object_or_404(queryset, pk=pk, company=company)


def printing_permission(permission):
    def decorator(view):
        @login_required
        @company_required
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not has_permission(request.user, permission):
                return HttpResponseForbidden("Sem permissão para esta operação de impressão.")
            response = view(request, *args, **kwargs)
            response["Cache-Control"] = "no-store"
            return response
        return wrapped
    return decorator


@printing_permission("can_manage_users")
@require_http_methods(["GET", "POST"])
def settings_view(request):
    company = request.current_company
    settings = PrintSettings.objects.filter(company=company).first() or PrintSettings(company=company)
    printer_form = PrinterForm(instance=Printer(company=company), auto_id="id_new_%s")
    settings_form = PrintSettingsForm(instance=settings, company=company)
    token = None
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "save_printer":
            printer_id = request.POST.get("printer_id")
            printer = printer_for_company(Printer, printer_id, company) if printer_id else Printer(company=company)
            printer_form = PrinterForm(request.POST, instance=printer, auto_id=f"id_printer_{printer.pk}_%s" if printer.pk else "id_new_%s")
            if printer_form.is_valid():
                printer_form.save()
                messages.success(request, "Impressora salva.")
                return redirect("printing:settings")
        elif action == "save_settings":
            settings_form = PrintSettingsForm(request.POST, instance=settings, company=company)
            if settings_form.is_valid():
                settings_form.save()
                messages.success(request, "Configuração salva.")
                return redirect("printing:settings")
        elif action in {"issue_token", "revoke_token"}:
            with transaction.atomic():
                printer = printer_for_company(Printer.objects.select_for_update(), request.POST.get("printer_id"), company)
                BridgeCredential.objects.filter(printer=printer, company=company, active=True).update(active=False)
                if action == "issue_token":
                    _credential, token = issue_credential(printer)
            if not token:
                messages.success(request, "Credenciais revogadas.")
                return redirect("printing:settings")
        else:
            return HttpResponseForbidden("Operação inválida.")
    printers = Printer.objects.filter(company=company).order_by("pk")
    printer_forms = [(p, printer_form if printer_form.instance.pk == p.pk else PrinterForm(instance=p, auto_id=f"id_printer_{p.pk}_%s")) for p in printers]
    if printer_form.instance.pk:
        printer_form = PrinterForm(instance=Printer(company=company), auto_id="id_new_%s")
    return render(request, "printing/prebeta4/settings.html", {
        "printer_form": printer_form, "settings_form": settings_form, "token": token,
        "printer_forms": printer_forms,
        "connector_download_url": (os.environ.get('PRINT_CONNECTOR_DOWNLOAD_URL', '')
            if urlsplit(os.environ.get('PRINT_CONNECTOR_DOWNLOAD_URL', '')).scheme == 'https' else ''),
        "connector_installer_available": (Path(django_settings.BASE_DIR) / 'print_bridge/dist/ConectorPracaPDV.exe').is_file(),
    })


@printing_permission("can_view_orders_panel")
@require_http_methods(["GET"])
def jobs_view(request):
    jobs = PrintJob.objects.filter(company=request.current_company).select_related("printer").order_by("-pk")
    return render(request, "printing/prebeta4/jobs.html", {
        "page": Paginator(jobs, 50).get_page(request.GET.get("page")),
        "can_reprint": has_permission(request.user, "can_approve_order"),
        "can_configure": has_permission(request.user, "can_manage_users"),
    })


@printing_permission("can_view_orders_panel")
@require_http_methods(["GET"])
def preview_view(request, job_id):
    job = get_object_or_404(PrintJob.objects.select_related("printer"), pk=job_id, company=request.current_company)
    return render(request, "printing/prebeta4/preview.html", {
        "job": job, "ticket_html": mark_safe(render_html(job.payload, job.printer.characters_per_line)),
        "ticket_text": render_text(job.payload, job.printer.characters_per_line),
    })


@printing_permission("can_approve_order")
@require_POST
def reprint_view(request, job_id):
    get_object_or_404(PrintJob, pk=job_id, company=request.current_company)
    try:
        reprint_job(job_id=job_id, company_id=request.current_company.pk)
        messages.success(request, "Reimpressão adicionada à fila com o mesmo snapshot.")
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    return redirect("printing:jobs")


@printing_permission("can_manage_users")
@require_POST
def uncertain_view(request, job_id):
    get_object_or_404(PrintJob, pk=job_id, company=request.current_company)
    if request.POST.get("confirmed") != "yes":
        messages.error(request, "Pare o bridge e confira a impressora antes de encerrar um trabalho incerto.")
    elif mark_uncertain(job_id=job_id, company_id=request.current_company.pk):
        messages.success(request, "Resultado incerto registrado como erro. Reimpressão depende de ação explícita.")
    return redirect("printing:jobs")
