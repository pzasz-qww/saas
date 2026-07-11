from django.contrib import admin
from django.core.exceptions import ObjectDoesNotExist

from .models import Sale, SaleItem


class SaleItemInline(admin.TabularInline):
    model = SaleItem
    extra = 1

    fields = (
        "product",
        "quantity",
        "unit_price",
        "unit_cost",
        "total_price",
        "total_cost",
    )

    readonly_fields = (
        "unit_price",
        "unit_cost",
        "total_price",
        "total_cost",
    )


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    inlines = [SaleItemInline]

    list_display = (
        "id",
        "company",
        "show_order",
        "payment_method",
        "status",
        "total_amount",
        "total_cost",
        "gross_profit",
        "created_by",
        "created_at",
    )

    list_filter = (
        "company",
        "payment_method",
        "status",
        "created_at",
    )

    search_fields = (
        "=id",
        "company__name",
        "=order__id",
        "created_by__username",
        "created_by__first_name",
        "created_by__last_name",
    )

    readonly_fields = (
        "show_order",
        "total_amount",
        "total_cost",
        "gross_profit",
        "created_by",
        "created_at",
    )

    ordering = ("-created_at",)

    fieldsets = (
        (
            "Dados principais",
            {
                "fields": (
                    "company",
                    "show_order",
                )
            },
        ),
        (
            "Pagamento",
            {
                "fields": (
                    "payment_method",
                    "status",
                )
            },
        ),
        (
            "Resultados",
            {
                "fields": (
                    "total_amount",
                    "total_cost",
                    "gross_profit",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Auditoria",
            {
                "fields": (
                    "created_by",
                    "created_at",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    def save_model(self, request, obj, form, change):
        if obj.created_by_id is None:
            obj.created_by = request.user

        super().save_model(request, obj, form, change)

    def show_order(self, obj):
        if not obj:
            return "-"

        try:
            order = obj.order
        except ObjectDoesNotExist:
            return "-"

        return f"Pedido #{order.id}"

    show_order.short_description = "Pedido"


@admin.register(SaleItem)
class SaleItemAdmin(admin.ModelAdmin):
    list_display = (
        "sale",
        "company",
        "product",
        "quantity",
        "unit_price",
        "unit_cost",
        "total_price",
        "total_cost",
        "created_at",
    )

    list_filter = (
        "company",
        "product",
        "created_at",
    )

    search_fields = (
        "product__name",
        "company__name",
        "=sale__id",
    )

    readonly_fields = (
        "unit_price",
        "unit_cost",
        "total_price",
        "total_cost",
        "created_at",
    )

    ordering = ("-created_at",)

    fieldsets = (
        (
            "Item da venda",
            {
                "fields": (
                    "sale",
                    "company",
                    "product",
                    "quantity",
                )
            },
        ),
        (
            "Valores",
            {
                "fields": (
                    "unit_price",
                    "unit_cost",
                    "total_price",
                    "total_cost",
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
