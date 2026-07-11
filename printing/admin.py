
from django.contrib import admin
from .models import Printer, PrintSettings, PrintJob


@admin.register(Printer)
class PrinterAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)
    ordering = ("name",)


@admin.register(PrintSettings)
class PrintSettingsAdmin(admin.ModelAdmin):
    list_display = ("id", "created_at")
    list_filter = ("created_at",)
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)
    date_hierarchy = "created_at"


@admin.register(PrintJob)
class PrintJobAdmin(admin.ModelAdmin):
    list_display = ("id", "created_at")
    list_filter = ("created_at",)
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
