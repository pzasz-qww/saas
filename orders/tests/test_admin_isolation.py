from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory, TestCase

from orders.admin import OrderAdmin
from orders.models import Order
from products.models import StockMovement
from sales.models import Sale

from .helpers import make_company, make_entry, make_order, make_product, make_unit, make_user


class OrderAdminCompanyIsolationTests(TestCase):
    def setUp(self):
        self.company = make_company(name="Empresa do operador")
        self.other_company = make_company(name="Outra empresa")
        self.user = make_user(company=self.company)
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        self.request = RequestFactory().post("/admin/orders/order/")
        self.request.user = self.user
        self.model_admin = OrderAdmin(Order, AdminSite())

    def test_queryset_contains_only_orders_from_the_operator_company(self):
        own_order, _items = make_order(company=self.company, lines=[])
        foreign_order, _items = make_order(company=self.other_company, lines=[])

        queryset = self.model_admin.get_queryset(self.request)

        self.assertQuerySetEqual(queryset, [own_order], ordered=False)
        self.assertNotIn(foreign_order, queryset)

    def test_bulk_approval_rejects_a_foreign_order_even_with_a_forged_queryset(self):
        unit = make_unit(company=self.other_company)
        product = make_product(company=self.other_company, unit=unit)
        entry = make_entry(product=product, quantity="3.00")
        foreign_order, _items = make_order(
            company=self.other_company,
            lines=[(product, "1.00", "10.00")],
        )

        with patch.object(self.model_admin, "message_user") as message_user:
            self.model_admin._approve_orders(
                self.request,
                Order.objects.filter(pk=foreign_order.pk),
                "pix",
                "Pix",
            )

        foreign_order.refresh_from_db()
        entry.refresh_from_db()
        self.assertEqual(foreign_order.status, "pre_sale")
        self.assertIsNone(foreign_order.sale_id)
        self.assertEqual(entry.remaining_quantity, entry.quantity_added)
        self.assertEqual(Sale.objects.count(), 0)
        self.assertEqual(StockMovement.objects.count(), 0)
        self.assertTrue(message_user.called)
        self.assertIn("outra empresa", message_user.call_args.args[1])
