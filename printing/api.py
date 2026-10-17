import json
from functools import wraps

from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import PrintJob
from .queue import authenticate, claim_next, finish_job


def bridge_only(view):
    @csrf_exempt
    @require_POST
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        header = request.headers.get("Authorization", "")
        credential = authenticate(header[7:]) if header.startswith("Bearer ") else None
        if credential is None:
            response = JsonResponse({"error": "Credencial de bridge inválida."}, status=401)
            response["WWW-Authenticate"] = "Bearer"
        else:
            response = view(request, credential, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response
    return wrapped


@bridge_only
def next_job(request, credential):
    job = claim_next(credential)
    if job is None:
        return JsonResponse({"job": None})
    printer = credential.printer
    return JsonResponse({"job": {
        "id": job.pk, "claim_token": str(job.claim_token), "payload": job.payload,
        "printer": {"identifier": str(printer.identifier), "paper_width": printer.paper_width,
                    "characters_per_line": printer.characters_per_line, "auto_cut": printer.auto_cut},
    }})


@bridge_only
def result(request, credential, job_id):
    if len(request.body) > 8192:
        return JsonResponse({"error": "Corpo muito grande."}, status=400)
    try:
        data = json.loads(request.body)
        if not isinstance(data, dict) or data.get("status") not in {"printed", "error"}:
            raise ValueError
        if data["status"] == "error" and not isinstance(data.get("error"), str):
            raise ValueError
        job = finish_job(credential=credential, job_id=job_id, claim_token=data.get("claim_token"), success=data["status"] == "printed", error=data.get("error", ""))
    except (ValueError, TypeError, UnicodeDecodeError):
        return JsonResponse({"error": "Resultado inválido."}, status=400)
    except PrintJob.DoesNotExist:
        return JsonResponse({"error": "Trabalho não encontrado para este claim."}, status=404)
    except ValidationError as exc:
        return JsonResponse({"error": "; ".join(exc.messages)}, status=409)
    return JsonResponse({"id": job.pk, "status": job.status})
