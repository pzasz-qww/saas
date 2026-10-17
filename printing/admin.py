from django.contrib import admin

from .models import BridgeCredential, ItemPrintContext, OrderPrintContext, Printer, PrintJob, PrintSettings


class PrintingReadOnlyAdmin(admin.ModelAdmin):
    """Global superuser diagnostics; tenant operations use printing views."""
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser


@admin.register(Printer)
class PrinterAdmin(PrintingReadOnlyAdmin):
    list_display = ("name", "company", "identifier", "active")
    list_filter = ("company", "active")


@admin.register(PrintJob)
class PrintJobAdmin(PrintingReadOnlyAdmin):
    list_display = ("id", "company", "order_reference", "status", "attempts", "created_at")
    list_filter = ("company", "status")
    exclude = ("claim_token",)


@admin.register(BridgeCredential)
class BridgeCredentialAdmin(PrintingReadOnlyAdmin):
    list_display = ("identifier", "company", "printer", "active", "created_at")
    exclude = ("secret_hash",)


admin.site.register(PrintSettings, PrintingReadOnlyAdmin)
admin.site.register(OrderPrintContext, PrintingReadOnlyAdmin)
admin.site.register(ItemPrintContext, PrintingReadOnlyAdmin)
