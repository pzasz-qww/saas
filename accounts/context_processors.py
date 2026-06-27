from accounts.permissions import (
    can_access_pdv,
    can_adjust_stock,
    can_create_stock_entry,
    can_manage_users,
    can_view_orders_panel,
    can_view_stock,
)


def menu_context(request):
    user = request.user

    if not user.is_authenticated:
        return {
            "menu_permissions": {
                "is_authenticated": False,
            }
        }

    return {
        "menu_permissions": {
            "is_authenticated": True,
            "username": user.username,
            "can_access_pdv": can_access_pdv(user),
            "can_view_orders_panel": can_view_orders_panel(user),
            "can_view_stock": can_view_stock(user),
            "can_create_stock_entry": can_create_stock_entry(user),
            "can_access_admin": user.is_staff or user.is_superuser,
            "can_manage_users": can_manage_users(user),
            "can_adjust_stock": can_adjust_stock(user),
        }
    }