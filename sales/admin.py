from django.contrib import admin

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
        "payment_method",
        "total_amount",
        "total_cost",
        "gross_profit",
        "created_by",
        "created_at",
    )

    list_filter = (
        "company",
        "payment_method",
        "created_at",
    )

    search_fields = ("id",)

    readonly_fields = (
        "total_amount",
        "total_cost",
        "gross_profit",
        "created_at",
    )

    fieldsets = (
        (
            "Venda",
            {
                "fields": (
                    "company",
                    "payment_method",
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


@admin.register(SaleItem)
class SaleItemAdmin(admin.ModelAdmin):
    list_display = (
        "sale",
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
        "sale__id",
    )

    readonly_fields = (
        "unit_price",
        "unit_cost",
        "total_price",
        "total_cost",
        "created_at",
    )