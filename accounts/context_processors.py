from accounts.permissions import (
    can_access_pdv,
    can_adjust_stock,
    can_create_stock_entry,
    can_manage_users,
    can_view_orders_panel,
    can_view_stock,
    get_current_company,
    get_user_profile,
    is_support_user,
)


def menu_context(request):
    user = request.user

    if not user.is_authenticated:
        return {
            "current_company": None,
            "current_profile": None,
            "is_support_mode": False,
            "is_support_user": False,
            "menu_permissions": {
                "is_authenticated": False,
            }
        }

    profile = get_user_profile(user)
    company = get_current_company(request)
    support_user = is_support_user(user)
    role_name = None if support_user else profile.role_name() if profile else None
    company_is_active = bool(company and company.active)

    return {
        "current_company": company,
        "current_profile": profile,
        "is_support_mode": support_user,
        "is_support_user": support_user,
        "menu_permissions": {
            "is_authenticated": True,
            "username": user.username,
            "company": company,
            "company_name": company.name if company else None,
            "role_name": role_name,
            "has_company": company is not None,
            "company_is_active": company_is_active,
            "is_support_mode": support_user,
            "is_support_user": support_user,
            "support_company_selected": company is not None,
            "can_access_pdv": can_access_pdv(user),
            "can_view_orders_panel": can_view_orders_panel(user),
            "can_view_stock": can_view_stock(user),
            "can_create_stock_entry": can_create_stock_entry(user),
            "can_access_admin": user.is_superuser,
            "can_manage_users": can_manage_users(user),
            "can_adjust_stock": can_adjust_stock(user),
        }
    }
