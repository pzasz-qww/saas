from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.middleware.csrf import rotate_token
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from accounts.permissions import (
    SUPPORT_COMPANY_SESSION_KEY,
    can_manage_users,
    clear_support_operational_session,
    company_required,
    get_current_company,
    support_user_required,
)
from companies.models import Company

from .models import PERMISSION_FIELDS, Profile


PERMISSION_LABELS = {
    "can_access_pdv": "Acessar PDV",
    "can_create_order": "Criar pré-venda/pedido",
    "can_approve_order": "Aprovar venda",
    "can_mark_delivered": "Marcar como entregue",
    "can_cancel_pre_sale": "Cancelar pré-venda",
    "can_cancel_paid_order": "Cancelar venda e devolver estoque",
    "can_discard_paid_order": "Descartar venda sem devolver estoque",
    "can_view_orders_panel": "Ver painel de pedidos",
    "can_view_stock": "Ver estoque",
    "can_view_reports": "Ver relatórios",
    "can_create_stock_entry": "Criar entrada de estoque",
    "can_adjust_stock": "Alterar/conferir estoque",
    "can_manage_users": "Gerenciar funcionários e funções",
}


def checkbox_value(request, field_name):
    return request.POST.get(field_name) == "on"


def build_permission_list(obj):
    permissions = []

    for field in PERMISSION_FIELDS:
        permissions.append(
            {
                "field": field,
                "label": PERMISSION_LABELS.get(field, field),
                "value": getattr(obj, field),
            }
        )

    return permissions


def get_valid_role(role):
    valid_roles = {choice[0] for choice in Profile.ROLE_CHOICES}

    if role in valid_roles:
        return role

    return "waiter"


def login_view(request):
    if request.user.is_authenticated:
        return redirect("orders:pdv")

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")

        user = authenticate(
            request,
            username=username,
            password=password,
        )

        if user is not None:
            login(request, user)
            return redirect("orders:pdv")

        messages.warning(request, "Usuário ou senha inválidos.")

    return render(request, "accounts/login.html")


def logout_view(request):
    logout(request)
    return redirect("accounts:login")


@login_required
@support_user_required
@require_GET
def support_companies(request):
    return render(
        request,
        "accounts/support_companies.html",
        {
            "companies": Company.objects.all().order_by("name"),
            "selected_company": get_current_company(request),
        },
    )


@login_required
@support_user_required
@require_POST
def select_support_company(request, company_id):
    company = get_object_or_404(
        Company,
        pk=company_id,
        active=True,
    )

    clear_support_operational_session(request)
    request.session[SUPPORT_COMPANY_SESSION_KEY] = company.pk
    request.session.cycle_key()
    rotate_token(request)

    messages.success(
        request,
        f"Modo suporte ativado para {company.name}.",
    )
    return redirect("orders:pdv")


@login_required
@support_user_required
@require_POST
def clear_support_company(request):
    clear_support_operational_session(request)
    request.session.pop(SUPPORT_COMPANY_SESSION_KEY, None)
    request.session.cycle_key()
    rotate_token(request)

    messages.success(request, "Empresa do modo suporte removida.")
    return redirect("accounts:support_companies")


@login_required
@company_required
def people_management(request):
    if not can_manage_users(request.user):
        messages.warning(request, "Você não tem permissão para gerenciar a equipe.")
        return redirect("orders:pdv")

    company = request.current_company

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "create_employee":
            username = request.POST.get("username", "").strip()
            first_name = request.POST.get("first_name", "").strip()
            password = request.POST.get("password", "").strip()
            role = get_valid_role(request.POST.get("role"))

            if not username:
                messages.warning(request, "Informe o usuário de acesso.")
                return redirect("accounts:people_management")

            if not password:
                messages.warning(request, "Informe uma senha inicial para o membro da equipe.")
                return redirect("accounts:people_management")

            if User.objects.filter(username=username).exists():
                messages.warning(request, "Já existe um usuário com esse nome.")
                return redirect("accounts:people_management")

            try:
                with transaction.atomic():
                    user = User.objects.create_user(
                        username=username,
                        password=password,
                        first_name=first_name,
                    )

                    profile = Profile(
                        user=user,
                        company=company,
                        role=role,
                    )
                    profile.apply_legacy_role_defaults()
                    profile.save()
            except IntegrityError:
                messages.warning(
                    request,
                    "Não foi possível criar o membro da equipe. Verifique os dados e tente novamente.",
                )
                return redirect("accounts:people_management")

            messages.success(request, f"Membro da equipe criado: {username}.")
            return redirect("accounts:people_management")

        if action == "update_profile":
            profile_id = request.POST.get("profile_id")

            profile = get_object_or_404(
                Profile,
                id=profile_id,
                company=company,
            )

            first_name = request.POST.get("first_name", "").strip()
            role = get_valid_role(request.POST.get("role"))
            is_active = request.POST.get("is_active") == "on"
            role_changed = profile.role != role

            profile.role = role

            if role_changed:
                profile.apply_legacy_role_defaults()

            profile.user.first_name = first_name
            profile.user.is_active = is_active
            profile.user.save(update_fields=["first_name", "is_active"])
            profile.save()

            if role_changed:
                messages.success(
                    request,
                    "Função atualizada e permissões padrão aplicadas.",
                )
            else:
                messages.success(request, f"Membro atualizado: {profile.user.username}.")

            return redirect("accounts:people_management")

        if action == "update_permissions":
            profile_id = request.POST.get("profile_id")

            profile = get_object_or_404(
                Profile,
                id=profile_id,
                company=company,
            )

            for field in PERMISSION_FIELDS:
                setattr(profile, field, checkbox_value(request, field))

            profile.save()

            messages.success(
                request,
                f"Permissões avançadas atualizadas para {profile.user.username}.",
            )

            return redirect("accounts:people_management")

    profiles = (
        Profile.objects
        .filter(company=company)
        .select_related("user", "company", "role_template")
        .order_by("user__first_name", "user__username")
    )

    profile_rows = []

    for profile in profiles:
        profile_rows.append(
            {
                "profile": profile,
                "display_name": profile.user.first_name or profile.user.username,
                "permissions": build_permission_list(profile),
            }
        )

    return render(
        request,
        "accounts/people_management.html",
        {
            "company": company,
            "profile_rows": profile_rows,
            "role_choices": Profile.ROLE_CHOICES,
        },
    )
