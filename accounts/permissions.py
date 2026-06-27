from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect

from companies.models import Company


def get_user_profile(user):
    if not user.is_authenticated:
        return None

    return getattr(user, "profile", None)


def get_user_company(user):
    profile = get_user_profile(user)

    if profile:
        return profile.company

    if user.is_superuser:
        return Company.objects.filter(active=True).first()

    return None


def has_permission(user, permission_name):
    if not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    profile = get_user_profile(user)

    if not profile:
        return False

    if profile.role == "owner":
        return True

    return bool(getattr(profile, permission_name, False))


def can_access_pdv(user):
    return has_permission(user, "can_access_pdv")


def can_create_order(user):
    return has_permission(user, "can_create_order")


def can_approve_order(user):
    return has_permission(user, "can_approve_order")


def can_mark_delivered(user):
    return has_permission(user, "can_mark_delivered")


def can_cancel_pre_sale(user):
    return has_permission(user, "can_cancel_pre_sale")


def can_cancel_paid_order(user):
    return has_permission(user, "can_cancel_paid_order")


def can_discard_paid_order(user):
    return has_permission(user, "can_discard_paid_order")


def can_view_orders_panel(user):
    return has_permission(user, "can_view_orders_panel")


def can_view_stock(user):
    return has_permission(user, "can_view_stock")


def can_create_stock_entry(user):
    return has_permission(user, "can_create_stock_entry")


def can_adjust_stock(user):
    return has_permission(user, "can_adjust_stock")


def can_view_reports(user):
    return has_permission(user, "can_view_reports")


def can_manage_users(user):
    return has_permission(user, "can_manage_users")


def permission_required_check(permission_function, redirect_to="orders:pdv"):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if permission_function(request.user):
                return view_func(request, *args, **kwargs)

            messages.warning(
                request,
                "Você não tem permissão para acessar essa função.",
            )

            return redirect(redirect_to)

        return wrapper

    return decorator