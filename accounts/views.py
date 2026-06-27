from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.db import IntegrityError
from django.shortcuts import get_object_or_404, redirect, render

from accounts.permissions import can_manage_users, get_user_company
from .models import PERMISSION_FIELDS, Profile, StaffRole


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


def people_management(request):
    if not request.user.is_authenticated:
        return redirect("accounts:login")

    if not can_manage_users(request.user):
        messages.warning(request, "Você não tem permissão para gerenciar funcionários.")
        return redirect("orders:pdv")

    company = get_user_company(request.user)

    if company is None:
        messages.warning(request, "Cadastre uma empresa antes de gerenciar funcionários.")
        return redirect("/admin/companies/company/")

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "create_role":
            role_name = request.POST.get("role_name", "").strip()

            if not role_name:
                messages.warning(request, "Informe o nome da função.")
                return redirect("accounts:people_management")

            try:
                role = StaffRole.objects.create(
                    company=company,
                    name=role_name,
                )

                for field in PERMISSION_FIELDS:
                    setattr(role, field, checkbox_value(request, field))

                role.save()

                messages.success(request, f"Função criada: {role.name}.")

            except IntegrityError:
                messages.warning(request, "Já existe uma função com esse nome.")

            return redirect("accounts:people_management")

        if action == "create_employee":
            username = request.POST.get("username", "").strip()
            first_name = request.POST.get("first_name", "").strip()
            password = request.POST.get("password", "").strip() or "123"
            role_id = request.POST.get("role_template")
            is_staff = request.POST.get("is_staff") == "on"

            if not username:
                messages.warning(request, "Informe o usuário do funcionário.")
                return redirect("accounts:people_management")

            if User.objects.filter(username=username).exists():
                messages.warning(request, "Já existe um usuário com esse nome.")
                return redirect("accounts:people_management")

            role_template = None

            if role_id:
                role_template = get_object_or_404(
                    StaffRole,
                    id=role_id,
                    company=company,
                )

            user = User.objects.create_user(
                username=username,
                password=password,
                first_name=first_name,
            )

            user.is_staff = is_staff
            user.save(update_fields=["is_staff"])

            profile = Profile.objects.create(
                user=user,
                company=company,
                role_template=role_template,
            )

            profile.apply_role_defaults()
            profile.save()

            messages.success(
                request,
                f"Funcionário criado: {username}. Senha: {password}",
            )

            return redirect("accounts:people_management")

        if action == "update_profile":
            profile_id = request.POST.get("profile_id")

            profile = get_object_or_404(
                Profile,
                id=profile_id,
                company=company,
            )

            role_id = request.POST.get("role_template")
            is_active = request.POST.get("is_active") == "on"
            is_staff = request.POST.get("is_staff") == "on"

            if role_id:
                profile.role_template = get_object_or_404(
                    StaffRole,
                    id=role_id,
                    company=company,
                )
            else:
                profile.role_template = None

            for field in PERMISSION_FIELDS:
                setattr(profile, field, checkbox_value(request, field))

            profile.save()

            profile.user.is_active = is_active
            profile.user.is_staff = is_staff
            profile.user.save(update_fields=["is_active", "is_staff"])

            messages.success(request, f"Permissões atualizadas para {profile.user.username}.")

            return redirect("accounts:people_management")

        if action == "apply_role_to_profile":
            profile_id = request.POST.get("profile_id")

            profile = get_object_or_404(
                Profile,
                id=profile_id,
                company=company,
            )

            profile.apply_role_defaults()
            profile.save()

            messages.success(
                request,
                f"Permissões padrão aplicadas para {profile.user.username}.",
            )

            return redirect("accounts:people_management")

    roles = StaffRole.objects.filter(company=company).order_by("name")
    profiles = (
        Profile.objects
        .filter(company=company)
        .select_related("user", "company", "role_template")
        .order_by("user__username")
    )

    profile_rows = []

    for profile in profiles:
        profile_rows.append(
            {
                "profile": profile,
                "role_template_id": profile.role_template_id,
                "permissions": build_permission_list(profile),
            }
        )

    return render(
        request,
        "accounts/people_management.html",
        {
            "company": company,
            "roles": roles,
            "profile_rows": profile_rows,
            "permission_fields": [
                {
                    "field": field,
                    "label": PERMISSION_LABELS.get(field, field),
                }
                for field in PERMISSION_FIELDS
            ],
        },
    )