from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect, render

from companies.models import Company


SUPPORT_COMPANY_SESSION_KEY = "support_company_id"

# Não há estado operacional persistido em sessão hoje. Esta lista protege a
# troca de empresa caso carrinho/filtros passem a ser armazenados nela.
SUPPORT_OPERATIONAL_SESSION_KEYS = {
    "cart",
    "cart_data",
    "pdv_cart",
    "order_filters",
    "orders_filter",
    "stock_filters",
    "report_filters",
}
SUPPORT_OPERATIONAL_SESSION_PREFIXES = (
    "cart_",
    "pdv_",
    "order_",
    "orders_",
    "stock_",
    "sale_",
    "sales_",
    "report_",
    "filter_",
)


def get_user_profile(user):
    if not getattr(user, "is_authenticated", False):
        return None

    return getattr(user, "profile", None)


def get_user_company(user):
    """Retorna exclusivamente a empresa permanente do usuário comum."""
    profile = get_user_profile(user)

    if profile is None:
        return None

    return profile.company


def is_support_user(user):
    return bool(
        getattr(user, "is_authenticated", False)
        and (user.is_staff or user.is_superuser)
    )


def get_current_company(request):
    """
    Resolve a empresa atual sem fallback automático.

    Usuários comuns usam somente Profile.company. Staff e superusuários usam
    somente a empresa escolhida explicitamente na sessão.
    """
    user = getattr(request, "user", None)

    if not getattr(user, "is_authenticated", False):
        return None

    session = getattr(request, "session", None)

    if not is_support_user(user):
        # Uma seleção antiga nunca deve sobreviver à remoção do acesso staff.
        if session is not None:
            session.pop(SUPPORT_COMPANY_SESSION_KEY, None)
        return get_user_company(user)

    if session is None:
        return None

    company_id = session.get(SUPPORT_COMPANY_SESSION_KEY)

    try:
        company_id = int(company_id)
    except (TypeError, ValueError):
        if company_id is not None:
            session.pop(SUPPORT_COMPANY_SESSION_KEY, None)
        return None

    if company_id <= 0:
        session.pop(SUPPORT_COMPANY_SESSION_KEY, None)
        return None

    company = Company.objects.filter(pk=company_id).first()

    if company is None:
        session.pop(SUPPORT_COMPANY_SESSION_KEY, None)

    return company


def clear_support_operational_session(request):
    """Remove somente estados operacionais que não podem atravessar empresas."""
    for key in list(request.session.keys()):
        if (
            key in SUPPORT_OPERATIONAL_SESSION_KEYS
            or key.startswith(SUPPORT_OPERATIONAL_SESSION_PREFIXES)
        ):
            request.session.pop(key, None)


def support_user_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not is_support_user(request.user):
            return render(
                request,
                "accounts/support_forbidden.html",
                status=403,
            )

        return view_func(request, *args, **kwargs)

    return wrapper


def company_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        company = get_current_company(request)

        if company is None or not company.active:
            return render(
                request,
                "accounts/company_required.html",
                {
                    "blocked_company": company,
                    "support_user": is_support_user(request.user),
                },
                status=403,
            )

        request.current_company = company
        return view_func(request, *args, **kwargs)

    return wrapper


def has_permission(user, permission_name):
    if not user.is_authenticated:
        return False

    # Toda view operacional usa company_required antes desta verificação.
    if is_support_user(user):
        return True

    profile = get_user_profile(user)

    if not profile or not profile.company.active:
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
