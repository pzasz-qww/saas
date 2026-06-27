from django.contrib import admin

from .models import Unit, Product, StockEntry, StockMovement


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ("name", "symbol", "company")
    search_fields = ("name", "symbol")
    list_filter = ("company",)


class StockEntryInline(admin.TabularInline):
    model = StockEntry
    extra = 1

    fields = (
        "entry_mode",
        "total_cost",
        "quantity_added",
        "package_quantity",
        "package_cost",
        "remaining_quantity",
        "notes",
    )

    readonly_fields = ("remaining_quantity",)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    inlines = [StockEntryInline]

    list_display = (
        "name",
        "company",
        "category",
        "unit",
        "sale_price",
        "show_current_stock",
        "show_average_cost",
        "show_profit_per_unit",
        "active",
    )

    search_fields = ("name", "category")
    list_filter = ("company", "category", "product_type", "active")

    fieldsets = (
        (
            "Produto",
            {
                "fields": (
                    "company",
                    "name",
                    "category",
                    "product_type",
                    "unit",
                    "sale_price",
                    "minimum_quantity",
                    "active",
                )
            },
        ),
    )

    def show_current_stock(self, obj):
        return obj.current_stock

    show_current_stock.short_description = "Estoque atual"

    def show_average_cost(self, obj):
        return f"R$ {obj.average_cost:.2f}"

    show_average_cost.short_description = "Custo médio"

    def show_profit_per_unit(self, obj):
        return f"R$ {obj.profit_per_unit:.2f}"

    show_profit_per_unit.short_description = "Lucro/un."


@admin.register(StockEntry)
class StockEntryAdmin(admin.ModelAdmin):
    list_display = (
        "product",
        "total_cost",
        "quantity_added",
        "remaining_quantity",
        "show_unit_cost",
        "show_expected_profit",
        "created_at",
    )

    search_fields = ("product__name", "notes")
    list_filter = ("company", "product", "entry_mode", "created_at")

    readonly_fields = (
        "remaining_quantity",
        "show_unit_cost",
        "show_potential_revenue",
        "show_expected_profit",
        "created_at",
    )

    fieldsets = (
        (
            "Entrada simples",
            {
                "fields": (
                    "company",
                    "product",
                    "entry_mode",
                    "total_cost",
                    "quantity_added",
                    "remaining_quantity",
                )
            },
        ),
        (
            "Detalhes opcionais",
            {
                "fields": (
                    "package_quantity",
                    "package_cost",
                    "notes",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Resultados calculados",
            {
                "fields": (
                    "show_unit_cost",
                    "show_potential_revenue",
                    "show_expected_profit",
                    "created_at",
                ),
            },
        ),
    )

    def save_model(self, request, obj, form, change):
        if obj.created_by_id is None:
            obj.created_by = request.user

        super().save_model(request, obj, form, change)

    def show_unit_cost(self, obj):
        return f"R$ {obj.unit_cost:.2f}"

    show_unit_cost.short_description = "Custo unitário"

    def show_potential_revenue(self, obj):
        return f"R$ {obj.potential_revenue:.2f}"

    show_potential_revenue.short_description = "Receita potencial"

    def show_expected_profit(self, obj):
        return f"R$ {obj.expected_profit:.2f}"

    show_expected_profit.short_description = "Lucro esperado"


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = (
        "product",
        "movement_type",
        "quantity",
        "sale_value",
        "cost_value",
        "reason",
        "created_by",
        "created_at",
    )

    search_fields = ("product__name", "reason", "notes")
    list_filter = ("company", "product", "movement_type", "created_at")

    readonly_fields = (
        "stock_entry",
        "sale_value",
        "cost_value",
        "created_by",
        "created_at",
    )

    fieldsets = (
        (
            "Movimento",
            {
                "fields": (
                    "company",
                    "product",
                    "movement_type",
                    "quantity",
                    "reason",
                )
            },
        ),
        (
            "Calculado automaticamente",
            {
                "fields": (
                    "stock_entry",
                    "sale_value",
                    "cost_value",
                    "created_by",
                    "created_at",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Observações",
            {
                "fields": ("notes",),
                "classes": ("collapse",),
            },
        ),
    )

    def save_model(self, request, obj, form, change):
        if obj.created_by_id is None:
            obj.created_by = request.user

        super().save_model(request, obj, form, change)