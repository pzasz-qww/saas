from django.contrib import admin

from .models import Profile, StaffRole


@admin.register(StaffRole)
class StaffRoleAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "company",
        "show_order_permissions",
        "show_stock_permissions",
        "show_admin_permissions",
        "can_access_pdv",
        "can_create_order",
        "can_approve_order",
        "can_view_stock",
        "can_adjust_stock",
        "can_manage_users",
        "created_at",
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

    readonly_fields = ("created_at",)
    ordering = ("company__name", "name")

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
        (
            "Auditoria",
            {
                "fields": ("created_at",),
                "classes": ("collapse",),
            },
        ),
    )

    def show_order_permissions(self, obj):
        permissions = []

        if obj.can_create_order:
            permissions.append("cria pedido")
        if obj.can_approve_order:
            permissions.append("aprova venda")
        if obj.can_mark_delivered:
            permissions.append("marca entregue")

        return ", ".join(permissions) or "-"

    show_order_permissions.short_description = "Pedidos"

    def show_stock_permissions(self, obj):
        permissions = []

        if obj.can_view_stock:
            permissions.append("vê estoque")
        if obj.can_create_stock_entry:
            permissions.append("entrada")
        if obj.can_adjust_stock:
            permissions.append("ajuste")

        return ", ".join(permissions) or "-"

    show_stock_permissions.short_description = "Estoque"

    def show_admin_permissions(self, obj):
        permissions = []

        if obj.can_view_reports:
            permissions.append("relatórios")
        if obj.can_manage_users:
            permissions.append("equipe")

        return ", ".join(permissions) or "-"

    show_admin_permissions.short_description = "Administração"


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "show_display_name",
        "company",
        "role",
        "role_template",
        "show_user_is_active",
        "show_order_permissions",
        "show_stock_permissions",
        "show_admin_permissions",
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
        "user__is_active",
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

    readonly_fields = (
        "show_display_name",
        "show_user_is_active",
        "created_at",
    )

    ordering = ("company__name", "user__first_name", "user__username")

    fieldsets = (
        (
            "Dados básicos",
            {
                "fields": (
                    "user",
                    "show_display_name",
                    "show_user_is_active",
                )
            },
        ),
        (
            "Empresa e função",
            {
                "fields": (
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
            "Estoque e relatórios",
            {
                "fields": (
                    "can_view_stock",
                    "can_create_stock_entry",
                    "can_adjust_stock",
                    "can_view_reports",
                )
            },
        ),
        (
            "Permissões administrativas",
            {
                "fields": (
                    "can_view_orders_panel",
                    "can_manage_users",
                )
            },
        ),
        (
            "Auditoria",
            {
                "fields": ("created_at",),
                "classes": ("collapse",),
            },
        ),
    )

    actions = (
        "apply_default_permissions",
    )

    def show_display_name(self, obj):
        if not obj or not obj.user_id:
            return "-"

        return obj.user.get_full_name() or obj.user.username

    show_display_name.short_description = "Nome visível"

    def show_user_is_active(self, obj):
        if not obj or not obj.user_id:
            return False

        return obj.user.is_active

    show_user_is_active.boolean = True
    show_user_is_active.short_description = "Usuário ativo"

    def show_order_permissions(self, obj):
        permissions = []

        if obj.can_create_order:
            permissions.append("cria pedido")
        if obj.can_approve_order:
            permissions.append("aprova venda")
        if obj.can_mark_delivered:
            permissions.append("marca entregue")

        return ", ".join(permissions) or "-"

    show_order_permissions.short_description = "Pedidos"

    def show_stock_permissions(self, obj):
        permissions = []

        if obj.can_view_stock:
            permissions.append("vê estoque")
        if obj.can_create_stock_entry:
            permissions.append("entrada")
        if obj.can_adjust_stock:
            permissions.append("ajuste")

        return ", ".join(permissions) or "-"

    show_stock_permissions.short_description = "Estoque"

    def show_admin_permissions(self, obj):
        permissions = []

        if obj.can_view_orders_panel:
            permissions.append("painel")
        if obj.can_view_reports:
            permissions.append("relatórios")
        if obj.can_manage_users:
            permissions.append("equipe")

        return ", ".join(permissions) or "-"

    show_admin_permissions.short_description = "Administração"

    def apply_default_permissions(self, request, queryset):
        for profile in queryset:
            profile.apply_role_defaults()
            profile.save()

    apply_default_permissions.short_description = "Aplicar permissões padrão da função/cargo"
