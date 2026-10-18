"""One-use, company-scoped setup files. Never contain a permanent credential."""
import hashlib
import json
import secrets
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse, JsonResponse, FileResponse, Http404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .api import bridge_only
from .models import ConnectorLink, Printer, PrintSettings
from .queue import issue_credential
from .views import printing_permission


@printing_permission('can_manage_users')
def installer(request):
    path = Path(settings.BASE_DIR) / 'print_bridge' / 'dist' / 'ConectorPracaPDV.exe'
    if not path.is_file():
        raise Http404('Instalador ainda não disponibilizado neste servidor. Solicite ao suporte.')
    return FileResponse(path.open('rb'), as_attachment=True, filename='ConectorPracaPDV.exe')


@printing_permission('can_manage_users')
@require_POST
def download_link(request):
    secret = secrets.token_urlsafe(32)
    ConnectorLink.objects.create(company=request.current_company,
        digest=hashlib.sha256(secret.encode()).hexdigest(),
        expires_at=timezone.now() + timedelta(minutes=10))
    response = HttpResponse(json.dumps({'version': 1,
        'server_url': request.build_absolute_uri('/').rstrip('/'),
        'company': request.current_company.name, 'link': secret}), content_type='application/json')
    response['Content-Disposition'] = 'attachment; filename="Conectar-impressora.pdvconnect"'
    response['Cache-Control'] = 'no-store'
    return response


def read_body(request):
    if len(request.body) > 4096:
        raise ValueError()
    data = json.loads(request.body)
    if not isinstance(data, dict):
        raise ValueError()
    return data


@csrf_exempt
@require_POST
def exchange(request):
    try:
        data = read_body(request)
        secret = data.get('link')
        if not isinstance(secret, str) or not 32 <= len(secret) <= 128:
            raise ValueError()
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'error': 'Arquivo de conexão inválido.'}, status=400)
    with transaction.atomic():
        link = ConnectorLink.objects.filter(digest=hashlib.sha256(secret.encode()).hexdigest(),
            company__active=True, used_at__isnull=True, expires_at__gt=timezone.now()).first()
        if not link or not ConnectorLink.objects.filter(pk=link.pk, used_at__isnull=True,
                expires_at__gt=timezone.now()).update(used_at=timezone.now()):
            return JsonResponse({'error': 'Vínculo expirado ou já utilizado. Baixe outro no SaaS.'}, status=410)
        printer = Printer.objects.create(company=link.company, name='Conector Windows', auto_cut=False)
        credential, token = issue_credential(printer)
    response = JsonResponse({'token': token, 'printer_identifier': str(printer.identifier),
        'company': link.company.name})
    response['Cache-Control'] = 'no-store'
    return response


@bridge_only
def configure(request, credential):
    try:
        data = read_body(request)
        name, columns = data.get('name'), data.get('columns')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
            raise ValueError()
        if type(columns) is not int or not 32 <= columns <= 64:
            raise ValueError()
        if type(data.get('cut')) is not bool or type(data.get('automatic')) is not bool:
            raise ValueError()
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'error': 'Configuração inválida.'}, status=400)
    with transaction.atomic():
        printer = Printer.objects.select_for_update().get(pk=credential.printer_id, company=credential.company)
        printer.name, printer.characters_per_line, printer.auto_cut = name.strip(), columns, data['cut']
        printer.save()
        prefs, _ = PrintSettings.objects.get_or_create(company=credential.company)
        prefs = PrintSettings.objects.select_for_update().get(pk=prefs.pk)
        if data['automatic']:
            prefs.default_printer, prefs.automatic = printer, True
            prefs.save()
        elif prefs.default_printer_id == printer.pk:
            prefs.automatic = False
            prefs.save()
    return JsonResponse({'configured': True})


@bridge_only
def status(request, credential):
    prefs = PrintSettings.objects.filter(company=credential.company).first()
    return JsonResponse({'company': credential.company.name,
        'automatic': bool(prefs and prefs.automatic and prefs.default_printer_id == credential.printer_id)})
