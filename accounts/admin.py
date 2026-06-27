from django.contrib import admin

from .models import Profile, StaffRole


@admin.register(StaffRole)
class StaffRoleAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "company",
        "can_access_pdv",
        "can_create_order",
        "can_approve_order",
        "can_view_stock",
        "can_adjust_stock",
        "can_manage_users",
    )

    list_filter = (
        "company",
        "can_access_pdv",
        "can_create_order",
        "can_approve_order",
        "can_adjust_stock",
        "can_manage_users",
    )

    search_fields = (
        "name",
        "company__name",
    )

    fieldsets = (
        (
            "Função",
            {
                "fields": (
                    "company",
                    "name",
                )
            },
        ),
        (
            "Pedidos e PDV",
            {
                "fields": (
                    "can_access_pdv",
                    "can_create_order",
                    "can_approve_order",
                    "can_mark_delivered",
                )
            },
        ),
        (
            "Cancelamentos e exceções",
            {
                "fields": (
                    "can_cancel_pre_sale",
                    "can_cancel_paid_order",
                    "can_discard_paid_order",
                )
            },
        ),
        (
            "Estoque",
            {
                "fields": (
                    "can_view_stock",
                    "can_create_stock_entry",
                    "can_adjust_stock",
                )
            },
        ),
        (
            "Painéis e administração",
            {
                "fields": (
                    "can_view_orders_panel",
                    "can_view_reports",
                    "can_manage_users",
                )
            },
        ),
    )


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "company",
        "role_template",
        "role",
        "can_access_pdv",
        "can_create_order",
        "can_approve_order",
        "can_view_orders_panel",
        "can_view_stock",
        "can_adjust_stock",
        "can_manage_users",
    )

    list_filter = (
        "company",
        "role_template",
        "role",
        "can_access_pdv",
        "can_create_order",
        "can_approve_order",
        "can_view_stock",
        "can_adjust_stock",
        "can_manage_users",
    )

    search_fields = (
        "user__username",
        "user__first_name",
        "user__last_name",
        "company__name",
        "role_template__name",
    )

    fieldsets = (
        (
            "Funcionário",
            {
                "fields": (
                    "user",
                    "company",
                    "role_template",
                    "role",
                )
            },
        ),
        (
            "Pedidos e PDV",
            {
                "fields": (
                    "can_access_pdv",
                    "can_create_order",
                    "can_approve_order",
                    "can_mark_delivered",
                )
            },
        ),
        (
            "Cancelamentos e exceções",
            {
                "fields": (
                    "can_cancel_pre_sale",
                    "can_cancel_paid_order",
                    "can_discard_paid_order",
                )
            },
        ),
        (
            "Estoque",
            {
                "fields": (
                    "can_view_stock",
                    "can_create_stock_entry",
                    "can_adjust_stock",
                )
            },
        ),
        (
            "Painéis e administração",
            {
                "fields": (
                    "can_view_orders_panel",
                    "can_view_reports",
                    "can_manage_users",
                )
            },
        ),
    )

    actions = (
        "apply_default_permissions",
    )

    def apply_default_permissions(self, request, queryset):
        for profile in queryset:
            profile.apply_role_defaults()
            profile.save()

    apply_default_permissions.short_description = "Aplicar permissões padrão da função/cargo"