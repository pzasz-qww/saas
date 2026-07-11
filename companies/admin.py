from django.contrib import admin
from .models import Company


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("name", "document", "phone", "active", "created_at")
    search_fields = ("name", "document", "phone")
    list_filter = ("active", "created_at")
    readonly_fields = ("created_at",)
    ordering = ("name",)
    date_hierarchy = "created_at"

    fieldsets = (
        (
            "Dados da empresa",
            {
                "fields": (
                    "name",
                    "document",
                    "phone",
                )
            },
        ),
        (
            "Status",
            {
                "fields": ("active",)
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
