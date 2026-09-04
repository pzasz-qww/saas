from django import forms
from django.contrib import admin

from accounts.permissions import get_user_company

from .category_names import normalize_category_name
from .models import (
    Category,
    Product,
    ProductComponent,
    StockEntry,
    StockMovement,
    Unit,
)


class CompanyScopedAdminMixin:
    company_field = "company"

    def get_queryset(self, request):
        queryset = super().get_queryset(request)

        if request.user.is_superuser:
            return queryset

        company = get_user_company(request.user)
        if company is None:
            return queryset.none()

        return queryset.filter(**{self.company_field: company})

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = tuple(super().get_readonly_fields(request, obj))

        if request.user.is_superuser or self.company_field in readonly_fields:
            return readonly_fields

        return (*readonly_fields, self.company_field)

    def get_list_filter(self, request):
        list_filter = tuple(super().get_list_filter(request))

        if request.user.is_superuser:
            return list_filter

        return tuple(item for item in list_filter if item != self.company_field)

    def has_add_permission(self, request):
        if not request.user.is_superuser and get_user_company(request.user) is None:
            return False

        return super().has_add_permission(request)

    def has_view_permission(self, request, obj=None):
        if not self._object_is_in_scope(request, obj):
            return False

        return super().has_view_permission(request, obj=obj)

    def has_change_permission(self, request, obj=None):
        if not self._object_is_in_scope(request, obj):
            return False

        return super().has_change_permission(request, obj=obj)

    def has_delete_permission(self, request, obj=None):
        if not self._object_is_in_scope(request, obj):
            return False

        return super().has_delete_permission(request, obj=obj)

    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser:
            obj.company = get_user_company(request.user)

        super().save_model(request, obj, form, change)

    def _object_is_in_scope(self, request, obj):
        if obj is None or request.user.is_superuser:
            return True

        company = get_user_company(request.user)
        return bool(company and obj.company_id == company.pk)


class CategoryAdminForm(forms.ModelForm):
    def __init__(self, *args, company_scope=None, **kwargs):
        self.company_scope = company_scope
        super().__init__(*args, **kwargs)

    class Meta:
        model = Category
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()
        company = cleaned_data.get("company")

        if company is None and self.instance.company_id:
            company = self.instance.company

        if company is None:
            company = self.company_scope

        normalized_name = normalize_category_name(cleaned_data.get("name"))
        if company and normalized_name:
            equivalent_categories = Category.objects.filter(
                company=company,
                normalized_name=normalized_name,
            ).exclude(pk=self.instance.pk)
            if equivalent_categories.exists():
                self.add_error(
                    "name",
                    "Já existe uma categoria equivalente nesta empresa.",
                )

        return cleaned_data


@admin.register(Category)
class CategoryAdmin(CompanyScopedAdminMixin, admin.ModelAdmin):
    form = CategoryAdminForm
    list_display = ("name", "company", "active", "created_at")
    search_fields = ("name", "normalized_name", "company__name")
    list_filter = ("company", "active")
    readonly_fields = ("normalized_name", "created_at")
    ordering = ("company__name", "name")
    list_select_related = ("company",)

    fieldsets = (
        (
            "Categoria",
            {
                "fields": (
                    "company",
                    "name",
                    "active",
                )
            },
        ),
        (
            "Auditoria",
            {
                "fields": ("normalized_name", "created_at"),
                "classes": ("collapse",),
            },
        ),
    )

    def get_form(self, request, obj=None, change=False, **kwargs):
        base_form = super().get_form(
            request,
            obj=obj,
            change=change,
            **kwargs,
        )
        company_scope = (
            None
            if request.user.is_superuser
            else get_user_company(request.user)
        )

        class RequestScopedCategoryForm(base_form):
            def __init__(self, *args, **form_kwargs):
                form_kwargs["company_scope"] = company_scope
                super().__init__(*args, **form_kwargs)

        return RequestScopedCategoryForm

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = tuple(super().get_readonly_fields(request, obj))

        if obj is not None and "company" not in readonly_fields:
            return (*readonly_fields, "company")

        return readonly_fields


class ProductAdminForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()
        company = cleaned_data.get("company")

        if company is None and self.instance.company_id:
            company = self.instance.company

        category = cleaned_data.get("category")
        if company and category and category.company_id != company.pk:
            self.add_error(
                "category",
                "Selecione uma categoria pertencente à empresa do produto.",
            )

        unit = cleaned_data.get("unit")
        if company and unit and unit.company_id != company.pk:
            self.add_error(
                "unit",
                "Selecione uma unidade pertencente à empresa do produto.",
            )

        return cleaned_data


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ("name", "symbol", "company")
    search_fields = ("name", "symbol", "company__name")
    list_filter = ("company",)
    ordering = ("company__name", "name")

    fieldsets = (
        (
            "Unidade",
            {
                "fields": (
                    "company",
                    "name",
                    "symbol",
                )
            },
        ),
    )


class StockEntryInline(admin.TabularInline):
    model = StockEntry
    extra = 0
    can_delete = False

    fields = (
        "entry_date",
        "expiration_date",
        "input_quantity",
        "input_unit",
        "total_cost",
        "quantity_added",
        "base_unit",
        "remaining_quantity",
        "notes",
    )

    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Product)
class ProductAdmin(CompanyScopedAdminMixin, admin.ModelAdmin):
    form = ProductAdminForm
    inlines = [StockEntryInline]

    list_display = (
        "name",
        "company",
        "category",
        "inventory_role",
        "sale_form",
        "stock_dimension",
        "product_type",
        "unit",
        "sale_price",
        "show_current_stock",
        "minimum_quantity",
        "show_average_cost",
        "show_profit_per_unit",
        "active",
    )

    search_fields = (
        "name",
        "company__name",
        "category__name",
        "category__normalized_name",
        "unit__name",
        "unit__symbol",
    )
    list_filter = (
        "company",
        ("category", admin.RelatedOnlyFieldListFilter),
        "inventory_role",
        "sale_form",
        "stock_dimension",
        "product_type",
        "active",
        ("unit", admin.RelatedOnlyFieldListFilter),
    )
    list_select_related = ("category", "company", "unit")
    readonly_fields = (
        "show_current_stock",
        "show_average_cost",
        "show_profit_per_unit",
        "created_at",
    )
    ordering = ("company__name", "category__name", "name")

    fieldsets = (
        (
            "Dados básicos",
            {
                "fields": (
                    "company",
                    "name",
                    "category",
                    "product_type",
                )
            },
        ),
        (
            "Preço e unidade",
            {
                "fields": (
                    "unit",
                    "sale_price",
                )
            },
        ),
        (
            "Domínio de estoque e venda",
            {
                "fields": (
                    "inventory_role",
                    "sale_form",
                    "stock_dimension",
                    "unit_description",
                    "dose_ml",
                    "portion_g",
                    "preparation_mode",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Controle de estoque",
            {
                "fields": (
                    "minimum_quantity",
                    "show_current_stock",
                    "show_average_cost",
                    "show_profit_per_unit",
                )
            },
        ),
        (
            "Status",
            {
                "fields": (
                    "active",
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

    def show_current_stock(self, obj):
        if not obj:
            return "-"

        return obj.current_stock

    show_current_stock.short_description = "Estoque atual"

    def show_average_cost(self, obj):
        if not obj:
            return "-"

        return f"R$ {obj.average_cost:.2f}"

    show_average_cost.short_description = "Custo médio"

    def show_profit_per_unit(self, obj):
        if not obj:
            return "-"

        return f"R$ {obj.profit_per_unit:.2f}"

    show_profit_per_unit.short_description = "Lucro/un."

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            "category",
            "company",
            "unit",
        )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if not request.user.is_superuser:
            company = get_user_company(request.user)

            if db_field.name == "category":
                kwargs["queryset"] = Category.objects.filter(company=company)
            elif db_field.name == "unit":
                kwargs["queryset"] = Unit.objects.filter(company=company)

        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser:
            obj.company = get_user_company(request.user)

        obj.category_legacy = obj.category.name if obj.category_id else None
        super().save_model(request, obj, form, change)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ProductComponent)
class ProductComponentAdmin(CompanyScopedAdminMixin, admin.ModelAdmin):
    list_display = (
        "product",
        "ingredient",
        "quantity",
        "unit",
        "company",
        "created_at",
    )
    search_fields = (
        "product__name",
        "ingredient__name",
        "company__name",
    )
    list_filter = ("company", "unit", "created_at")
    list_select_related = ("company", "product", "ingredient")
    readonly_fields = ("created_at",)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if not request.user.is_superuser and db_field.name in {"product", "ingredient"}:
            company = get_user_company(request.user)
            queryset = Product.objects.filter(company=company)
            if db_field.name == "product":
                queryset = queryset.filter(inventory_role="prepared")
            else:
                queryset = queryset.exclude(inventory_role="prepared")
            kwargs["queryset"] = queryset.order_by("name")

        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser:
            obj.company = get_user_company(request.user)

        super().save_model(request, obj, form, change)


@admin.register(StockEntry)
class StockEntryAdmin(admin.ModelAdmin):
    list_display = (
        "product",
        "company",
        "input_quantity",
        "input_unit",
        "quantity_added",
        "base_unit",
        "total_cost",
        "remaining_quantity",
        "show_unit_cost",
        "entry_date",
        "expiration_date",
        "created_by",
        "show_expected_profit",
        "created_at",
    )

    search_fields = ("product__name", "company__name", "notes", "created_by__username")
    list_filter = (
        "company",
        "product",
        "input_unit",
        "entry_date",
        "expiration_date",
        "created_by",
        "created_at",
    )

    readonly_fields = (
        "company",
        "product",
        "entry_date",
        "expiration_date",
        "input_quantity",
        "input_unit",
        "total_cost",
        "quantity_added",
        "base_unit",
        "remaining_quantity",
        "notes",
        "show_unit_cost",
        "show_potential_revenue",
        "show_expected_profit",
        "created_by",
        "created_at",
    )

    ordering = ("-created_at",)

    fieldsets = (
        (
            "Entrada",
            {
                "fields": (
                    "company",
                    "product",
                    "entry_date",
                    "expiration_date",
                )
            },
        ),
        (
            "Quantidade e custo",
            {
                "fields": (
                    "input_quantity",
                    "input_unit",
                    "total_cost",
                    "quantity_added",
                    "base_unit",
                    "remaining_quantity",
                )
            },
        ),
        (
            "Detalhes opcionais",
            {
                "fields": (
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
                ),
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

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def show_unit_cost(self, obj):
        if not obj:
            return "-"

        return f"R$ {obj.unit_cost:.2f}"

    show_unit_cost.short_description = "Custo unitário"

    def show_potential_revenue(self, obj):
        if not obj:
            return "-"

        return f"R$ {obj.potential_revenue:.2f}"

    show_potential_revenue.short_description = "Receita potencial"

    def show_expected_profit(self, obj):
        if not obj:
            return "-"

        return f"R$ {obj.expected_profit:.2f}"

    show_expected_profit.short_description = "Lucro esperado"


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = (
        "product",
        "company",
        "movement_type",
        "quantity",
        "sale_value",
        "cost_value",
        "reason",
        "created_by",
        "created_at",
    )

    search_fields = ("product__name", "company__name", "reason", "notes", "created_by__username")
    list_filter = ("company", "product", "movement_type", "created_by", "created_at")

    readonly_fields = (
        "company",
        "product",
        "stock_entry",
        "sale_item",
        "reversal_of",
        "movement_type",
        "quantity",
        "sale_value",
        "cost_value",
        "reason",
        "notes",
        "created_by",
        "created_at",
    )

    ordering = ("-created_at",)

    fieldsets = (
        (
            "Movimento",
            {
                "fields": (
                    "company",
                    "product",
                    "sale_item",
                    "reversal_of",
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

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
