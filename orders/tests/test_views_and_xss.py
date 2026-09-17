from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from django.utils.html import conditional_escape

from orders.services import approve_order
from products.models import StockMovement
from sales.models import Sale

from .helpers import (
    OrderTestMixin,
    make_company,
    make_entry,
    make_order,
    make_product,
    make_unit,
    make_user,
)


class OrderWorkflowViewTests(OrderTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def test_approval_view_shows_understandable_insufficient_stock_message(self):
        product = self.make_product()
        entry = make_entry(product=product, quantity="4.00")
        order, _items = self.make_order([(product, "5.00", "10.00")])

        response = self.client.post(
            reverse(
                "orders:approve_order",
                args=[order.pk, "pix"],
            ),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "A quantidade disponível")
        self.assertContains(response, "Disponível agora: 4")
        self.assertContains(response, "Solicitado: 5 unidades")
        order.refresh_from_db()
        entry.refresh_from_db()
        self.assertEqual(order.status, "pre_sale")
        self.assertIsNone(order.sale_id)
        self.assertEqual(entry.remaining_quantity, entry.quantity_added)
        self.assertEqual(Sale.objects.count(), 0)
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_duplicate_approval_view_reports_that_order_was_already_approved(self):
        product = self.make_product()
        make_entry(product=product, quantity="5.00")
        order, _items = self.make_order([(product, "1.00", "10.00")])
        approve_order(
            order_id=order.pk,
            company=self.company,
            payment_method="pix",
            user=self.user,
        )

        response = self.client.post(
            reverse(
                "orders:approve_order",
                args=[order.pk, "pix"],
            ),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "já estava aprovado")
        self.assertEqual(Sale.objects.count(), 1)
        self.assertEqual(
            StockMovement.objects.filter(movement_type="sale").count(),
            1,
        )

    def test_legacy_cancellation_view_explains_why_return_is_refused(self):
        product = self.make_product()
        entry = make_entry(product=product, quantity="5.00")
        order, _items = self.make_order([(product, "2.00", "10.00")])
        approve_order(
            order_id=order.pk,
            company=self.company,
            payment_method="pix",
            user=self.user,
        )
        StockMovement.objects.filter(movement_type="sale").update(sale_item=None)

        response = self.client.post(
            reverse(
                "orders:cancel_paid_order_with_stock_return",
                args=[order.pk],
            ),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "venda é legada")
        order.refresh_from_db()
        entry.refresh_from_db()
        self.assertEqual(order.status, "sold")
        self.assertEqual(entry.remaining_quantity, entry.quantity_added - 2)
        self.assertFalse(
            StockMovement.objects.filter(
                movement_type="return_to_stock"
            ).exists()
        )

    def test_approval_view_is_scoped_to_authenticated_company(self):
        product = self.make_product()
        entry = make_entry(product=product, quantity="5.00")
        order, _items = self.make_order([(product, "1.00", "10.00")])
        other_company = make_company(name="Outra empresa")
        other_user = make_user(company=other_company)
        self.client.force_login(other_user)

        response = self.client.post(
            reverse(
                "orders:approve_order",
                args=[order.pk, "pix"],
            )
        )

        self.assertEqual(response.status_code, 404)
        order.refresh_from_db()
        entry.refresh_from_db()
        self.assertEqual(order.status, "pre_sale")
        self.assertEqual(entry.remaining_quantity, entry.quantity_added)
        self.assertEqual(Sale.objects.count(), 0)


class PdvXssRegressionTests(TestCase):
    def setUp(self):
        self.company = make_company()
        self.user = make_user(company=self.company)
        self.unit = make_unit(company=self.company)
        self.client.force_login(self.user)

    def test_persisted_product_name_is_html_escaped_and_not_used_in_inline_code(self):
        payload = (
            "<script>window.__pdv_xss = true</script> "
            "< > \" ' ` &lt;script&gt;"
        )
        make_product(
            company=self.company,
            unit=self.unit,
            name=payload,
            sale_price="10.00",
        )

        response = self.client.get(reverse("orders:pdv"))
        html = response.content.decode("utf-8")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(payload, html)
        self.assertNotIn("<script>window.__pdv_xss", html)
        self.assertIn(str(conditional_escape(payload)), html)
        self.assertNotIn("onclick=", html.lower())
        self.assertNotIn("onsubmit=", html.lower())
        self.assertIn("data-product-name=", html)

    def test_cart_javascript_uses_dom_text_apis_for_persisted_names(self):
        script = Path(settings.BASE_DIR, "static", "js", "pdv.js").read_text(
            encoding="utf-8"
        )

        self.assertIn("textContent", script)
        self.assertIn("addEventListener", script)
        self.assertIn("dataset.productName", script)
        self.assertNotIn("innerHTML", script)
        self.assertNotIn("onclick", script)
