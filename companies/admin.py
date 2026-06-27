from django.contrib import admin
from .models import Company


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("name", "document", "phone", "active", "created_at")
    search_fields = ("name", "document", "phone")
    list_filter = ("active",)