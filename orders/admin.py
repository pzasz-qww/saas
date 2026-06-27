from django.contrib import admin, messages

from .models import Order, OrderItem


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 1

    fields = (
        "product",
        "quantity",
        "unit_price",
        "total_price",
        "notes",
    )

    readonly_fields = (
        "unit_price",
        "total_price",
    )


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    inlines = [OrderItemInline]

    list_display = (
        "id",
        "company",
        "table_or_tab",
        "status",
        "total_amount",
        "created_by",
        "approved_by",
        "created_at",
    )

    list_filter = (
        "company",
        "status",
        "created_at",
    )

    search_fields = (
        "id",
        "table_or_tab",
        "created_by__username",
    )

    readonly_fields = (
        "total_amount",
        "approved_by",
        "approved_at",
        "delivered_at",
        "sale",
        "created_at",
    )

    fieldsets = (
        (
            "Pedido",
            {
                "fields": (
                    "company",
                    "table_or_tab",
                    "status",
                    "notes",
                )
            },
        ),
        (
            "Resultado",
            {
                "fields": (
                    "total_amount",
                    "sale",
                )
            },
        ),
        (
            "Auditoria",
            {
                "fields": (
                    "created_by",
                    "approved_by",
                    "approved_at",
                    "delivered_at",
                    "created_at",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    actions = (
        "approve_pix",
        "approve_cash",
        "approve_debit",
        "approve_credit",
        "mark_delivered",
        "cancel_orders",
    )

    def save_model(self, request, obj, form, change):
        if obj.created_by_id is None:
            obj.created_by = request.user

        super().save_model(request, obj, form, change)

    def approve_pix(self, request, queryset):
        for order in queryset:
            order.approve(payment_method="pix", user=request.user)

        self.message_user(request, "Pedido(s) aprovado(s) como Pix.", messages.SUCCESS)

    approve_pix.short_description = "Aprovar como Pix"

    def approve_cash(self, request, queryset):
        for order in queryset:
            order.approve(payment_method="cash", user=request.user)

        self.message_user(request, "Pedido(s) aprovado(s) como Dinheiro.", messages.SUCCESS)

    approve_cash.short_description = "Aprovar como Dinheiro"

    def approve_debit(self, request, queryset):
        for order in queryset:
            order.approve(payment_method="debit", user=request.user)

        self.message_user(request, "Pedido(s) aprovado(s) como Débito.", messages.SUCCESS)

    approve_debit.short_description = "Aprovar como Débito"

    def approve_credit(self, request, queryset):
        for order in queryset:
            order.approve(payment_method="credit", user=request.user)

        self.message_user(request, "Pedido(s) aprovado(s) como Crédito.", messages.SUCCESS)

    approve_credit.short_description = "Aprovar como Crédito"

    def mark_delivered(self, request, queryset):
        for order in queryset:
            order.mark_delivered()

        self.message_user(request, "Pedido(s) marcado(s) como entregue.", messages.SUCCESS)

    mark_delivered.short_description = "Marcar como entregue"

    def cancel_orders(self, request, queryset):
        for order in queryset:
            order.cancel()

        self.message_user(request, "Pedido(s) cancelado(s).", messages.WARNING)

    cancel_orders.short_description = "Cancelar pedido(s)"


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = (
        "order",
        "product",
        "quantity",
        "unit_price",
        "total_price",
        "created_at",
    )

    list_filter = (
        "company",
        "product",
        "created_at",
    )

    search_fields = (
        "product__name",
        "order__id",
    )

    readonly_fields = (
        "unit_price",
        "total_price",
        "created_at",
    )