from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from products.admin import ProductAdmin, StockEntryAdmin, StockMovementAdmin
from products.models import Product, StockEntry, StockMovement


class StockAdminProtectionTests(TestCase):
    def setUp(self):
        self.request = RequestFactory().get("/admin/")
        self.request.user = get_user_model().objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="secret",
        )
        self.site = AdminSite()

    def test_entries_are_consultation_only(self):
        model_admin = StockEntryAdmin(StockEntry, self.site)

        self.assertFalse(model_admin.has_add_permission(self.request))
        self.assertFalse(model_admin.has_change_permission(self.request))
        self.assertFalse(model_admin.has_delete_permission(self.request))

    def test_movements_are_consultation_only(self):
        model_admin = StockMovementAdmin(StockMovement, self.site)

        self.assertFalse(model_admin.has_add_permission(self.request))
        self.assertFalse(model_admin.has_change_permission(self.request))
        self.assertFalse(model_admin.has_delete_permission(self.request))

    def test_products_cannot_be_deleted_through_admin(self):
        model_admin = ProductAdmin(Product, self.site)

        self.assertFalse(model_admin.has_delete_permission(self.request))
