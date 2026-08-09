from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from sales.admin import SaleAdmin, SaleItemAdmin
from sales.models import Sale, SaleItem


class SaleAdminProtectionTests(TestCase):
    def setUp(self):
        self.request = RequestFactory().get("/admin/")
        self.request.user = get_user_model().objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="secret",
        )
        self.site = AdminSite()

    def test_sales_are_consultation_only(self):
        model_admin = SaleAdmin(Sale, self.site)

        self.assertFalse(model_admin.has_add_permission(self.request))
        self.assertFalse(model_admin.has_change_permission(self.request))
        self.assertFalse(model_admin.has_delete_permission(self.request))

    def test_sale_items_are_consultation_only(self):
        model_admin = SaleItemAdmin(SaleItem, self.site)

        self.assertFalse(model_admin.has_add_permission(self.request))
        self.assertFalse(model_admin.has_change_permission(self.request))
        self.assertFalse(model_admin.has_delete_permission(self.request))
