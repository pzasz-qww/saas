from django.contrib import admin, messages

from accounts.permissions import get_user_company
from products.services import StockServiceError

from .models import Order, OrderItem
from .services import OrderServiceError, approve_order


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0

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

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.status != "pre_sale":
            return self.fields

        return self.readonly_fields

    def has_add_permission(self, request, obj=None):
        return bool(obj and obj.status == "pre_sale")

    def has_delete_permission(self, request, obj=None):
        return bool(obj and obj.status == "pre_sale")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    inlines = [OrderItemInline]

    list_display = (
        "id",
        "company",
        "table_or_tab",
        "status",
        "show_payment_method",
        "total_amount",
        "created_by",
        "approved_by",
        "created_at",
    )

    list_filter = (
        "company",
        "status",
        "sale__payment_method",
        "created_at",
    )

    search_fields = (
        "=id",
        "company__name",
        "table_or_tab",
        "created_by__username",
        "created_by__first_name",
        "created_by__last_name",
    )

    readonly_fields = (
        "company",
        "status",
        "total_amount",
        "show_payment_method",
        "created_by",
        "approved_by",
        "approved_at",
        "delivered_at",
        "sale",
        "created_at",
    )

    ordering = ("-created_at",)

    fieldsets = (
        (
            "Dados principais",
            {
                "fields": (
                    "company",
                    "table_or_tab",
                    "notes",
                )
            },
        ),
        (
            "Pagamento e status",
            {
                "fields": (
                    "status",
                    "show_payment_method",
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

    def get_queryset(self, request):
        queryset = super().get_queryset(request)

        if request.user.is_superuser:
            return queryset

        company = get_user_company(request.user)
        if company is None:
            return queryset.none()

        return queryset.filter(company=company)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        if obj is not None and obj.status != "pre_sale":
            return False

        return super().has_change_permission(request, obj=obj)

    def has_delete_permission(self, request, obj=None):
        return False

    def show_payment_method(self, obj):
        if not obj or not obj.sale_id:
            return "-"

        return obj.sale.get_payment_method_display()

    show_payment_method.short_description = "Pagamento"

    def approve_pix(self, request, queryset):
        self._approve_orders(request, queryset, "pix", "Pix")

    approve_pix.short_description = "Aprovar como Pix"

    def approve_cash(self, request, queryset):
        self._approve_orders(request, queryset, "cash", "Dinheiro")

    approve_cash.short_description = "Aprovar como Dinheiro"

    def approve_debit(self, request, queryset):
        self._approve_orders(request, queryset, "debit", "Débito")

    approve_debit.short_description = "Aprovar como Débito"

    def approve_credit(self, request, queryset):
        self._approve_orders(request, queryset, "credit", "Crédito")

    approve_credit.short_description = "Aprovar como Crédito"

    def _approve_orders(self, request, queryset, payment_method, payment_label):
        approved = 0
        already_approved = 0
        failures = []
        request_company = None

        if not request.user.is_superuser:
            request_company = get_user_company(request.user)

        for order in queryset.order_by("id"):
            if request_company is None and not request.user.is_superuser:
                failures.append(f"#{order.id}: usuário sem empresa vinculada.")
                continue

            company = order.company if request.user.is_superuser else request_company
            if order.company_id != company.pk:
                failures.append(f"#{order.id}: pedido pertence a outra empresa.")
                continue

            try:
                result = approve_order(
                    order_id=order.id,
                    company=company,
                    payment_method=payment_method,
                    user=request.user,
                )
            except (OrderServiceError, StockServiceError) as error:
                failures.append(f"#{order.id}: {error}")
            else:
                if result.created:
                    approved += 1
                else:
                    already_approved += 1

        if approved:
            self.message_user(
                request,
                f"{approved} pedido(s) aprovado(s) como {payment_label}.",
                messages.SUCCESS,
            )

        if already_approved:
            self.message_user(
                request,
                f"{already_approved} pedido(s) já estavam aprovados.",
                messages.INFO,
            )

        if failures:
            self.message_user(request, " | ".join(failures), messages.WARNING)

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
        "company",
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
        "company__name",
        "=order__id",
    )

    readonly_fields = (
        "unit_price",
        "total_price",
        "created_at",
    )

    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    fieldsets = (
        (
            "Item do pedido",
            {
                "fields": (
                    "order",
                    "company",
                    "product",
                    "quantity",
                    "notes",
                )
            },
        ),
        (
            "Valores",
            {
                "fields": (
                    "unit_price",
                    "total_price",
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
