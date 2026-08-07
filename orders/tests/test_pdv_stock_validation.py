import json

from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from orders.models import Order, OrderItem
from orders.services import approve_order
from orders.views import PDV_DRAFT_SESSION_KEY
from products.models import StockMovement
from products.services import InsufficientStock
from sales.models import Sale

from .helpers import (
    OrderTestMixin,
    make_company,
    make_entry,
    make_order,
    make_product,
    make_unit,
)


class PdvStockValidationTests(OrderTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def post_cart(self, items):
        response = self.client.post(
            reverse("orders:pdv"),
            {
                "table_or_tab": "Mesa 7",
                "cart_data": json.dumps(items),
            },
        )
        message_text = "\n".join(
            str(message) for message in get_messages(response.wsgi_request)
        )
        return response, message_text

    def assert_nothing_was_created_or_moved(self):
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(OrderItem.objects.count(), 0)
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_product_without_stock_rejects_entire_pre_sale(self):
        product = self.make_product(name="Heineken sem saldo")

        response, message = self.post_cart(
            [{"id": product.pk, "quantity": 1}]
        )

        self.assertRedirects(
            response,
            reverse("orders:pdv"),
            fetch_redirect_response=False,
        )
        self.assertIn(product.name, message)
        self.assertIn("sem estoque", message.lower())
        self.assert_nothing_was_created_or_moved()

    def test_stock_error_is_visible_and_preserves_the_validated_cart(self):
        product = self.make_product(name="Produto para corrigir")

        response = self.client.post(
            reverse("orders:pdv"),
            {
                "table_or_tab": "Mesa preservada",
                "cart_data": json.dumps(
                    [{"id": product.pk, "quantity": 2}]
                ),
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Não foi possível enviar a pré-venda")
        self.assertContains(response, product.name)
        self.assertContains(response, 'value="Mesa preservada"', html=False)
        self.assertEqual(
            response.context["initial_cart"],
            [
                {
                    "id": str(product.pk),
                    "name": product.name,
                    "price": str(product.sale_price),
                    "quantity": 2,
                }
            ],
        )
        self.assert_nothing_was_created_or_moved()

    def test_quantity_above_available_stock_reports_requested_and_available(self):
        product = self.make_product(name="Vodka limitado")
        entry = make_entry(product=product, quantity="2.00")

        _response, message = self.post_cart(
            [{"id": product.pk, "quantity": 5}]
        )

        self.assertIn(product.name, message)
        self.assertIn("solicitadas 5", message.lower())
        self.assertIn("disponíveis 2", message.lower())
        self.assert_nothing_was_created_or_moved()
        entry.refresh_from_db()
        self.assertEqual(entry.remaining_quantity, entry.quantity_added)

    def test_one_insufficient_item_prevents_all_items_from_being_created(self):
        available_product = self.make_product(name="Produto disponível")
        unavailable_product = self.make_product(name="Produto indisponível")
        available_entry = make_entry(
            product=available_product,
            quantity="10.00",
        )

        _response, message = self.post_cart(
            [
                {"id": available_product.pk, "quantity": 2},
                {"id": unavailable_product.pk, "quantity": 1},
            ]
        )

        self.assertIn(unavailable_product.name, message)
        self.assertIn("sem estoque", message.lower())
        self.assert_nothing_was_created_or_moved()
        available_entry.refresh_from_db()
        self.assertEqual(
            available_entry.remaining_quantity,
            available_entry.quantity_added,
        )

    def test_all_insufficient_items_are_presented_in_the_same_message(self):
        beer = self.make_product(name="Cerveja insuficiente")
        vodka = self.make_product(name="Vodka zerada")
        make_entry(product=beer, quantity="2.00")

        _response, message = self.post_cart(
            [
                {"id": beer.pk, "quantity": 5},
                {"id": vodka.pk, "quantity": 1},
            ]
        )

        self.assertIn(beer.name, message)
        self.assertIn("solicitadas 5", message.lower())
        self.assertIn("disponíveis 2", message.lower())
        self.assertIn(vodka.name, message)
        self.assertIn("sem estoque", message.lower())
        self.assert_nothing_was_created_or_moved()

    def test_exact_stock_creates_pre_sale_without_consuming_stock(self):
        product = self.make_product(name="Estoque exato")
        entry = make_entry(product=product, quantity="5.00")

        response, _message = self.post_cart(
            [{"id": product.pk, "quantity": 5}]
        )

        order = Order.objects.get()
        self.assertRedirects(
            response,
            reverse("orders:order_detail", args=[order.pk]),
            fetch_redirect_response=False,
        )
        item = OrderItem.objects.get(order=order)
        self.assertEqual(item.product, product)
        self.assertEqual(item.quantity, 5)
        entry.refresh_from_db()
        self.assertEqual(entry.remaining_quantity, entry.quantity_added)
        self.assertFalse(StockMovement.objects.exists())

    def test_stock_above_requested_creates_pre_sale_without_movement(self):
        product = self.make_product(name="Estoque folgado")
        entry = make_entry(product=product, quantity="10.00")

        _response, _message = self.post_cart(
            [{"id": product.pk, "quantity": 3}]
        )

        order = Order.objects.get()
        item = OrderItem.objects.get(order=order)
        self.assertEqual(item.quantity, 3)
        entry.refresh_from_db()
        self.assertEqual(entry.remaining_quantity, 10)
        self.assertFalse(StockMovement.objects.exists())

    def test_repeated_product_is_aggregated_before_stock_validation(self):
        product = self.make_product(name="Produto repetido")
        entry = make_entry(product=product, quantity="4.00")

        _response, message = self.post_cart(
            [
                {"id": product.pk, "quantity": 2},
                {"id": product.pk, "quantity": 3},
            ]
        )

        self.assertIn(product.name, message)
        self.assertIn("solicitadas 5", message.lower())
        self.assertIn("disponíveis 4", message.lower())
        self.assert_nothing_was_created_or_moved()
        entry.refresh_from_db()
        self.assertEqual(entry.remaining_quantity, entry.quantity_added)

    def test_product_from_another_company_is_rejected_without_data_leak(self):
        other_company = make_company(name="Empresa confidencial")
        other_unit = make_unit(company=other_company)
        secret_product = make_product(
            company=other_company,
            unit=other_unit,
            name="Produto confidencial de outra empresa",
        )
        make_entry(product=secret_product, quantity="10.00")

        response, message = self.post_cart(
            [{"id": secret_product.pk, "quantity": 1}]
        )

        self.assertRedirects(
            response,
            reverse("orders:pdv"),
            fetch_redirect_response=False,
        )
        self.assertIn("Confira os itens do carrinho", message)
        self.assertNotIn(secret_product.name, message)
        self.assertNotIn(other_company.name, message)
        self.assert_nothing_was_created_or_moved()

    def test_internal_use_product_is_rejected_from_forged_payload(self):
        product = self.make_product(
            name="Produto somente de uso interno",
            product_type="internal_use",
        )
        make_entry(product=product, quantity="10.00")

        response, message = self.post_cart(
            [{"id": product.pk, "quantity": 1}]
        )

        self.assertRedirects(
            response,
            reverse("orders:pdv"),
            fetch_redirect_response=False,
        )
        self.assertIn("Confira os itens do carrinho", message)
        self.assertNotIn(product.name, message)
        self.assert_nothing_was_created_or_moved()

    def test_inactive_product_is_rejected_from_forged_payload(self):
        product = self.make_product(name="Produto inativo")
        product.active = False
        product.save(update_fields=["active"])
        make_entry(product=product, quantity="10.00")

        _response, message = self.post_cart(
            [{"id": product.pk, "quantity": 1}]
        )

        self.assertIn("Confira os itens do carrinho", message)
        self.assertNotIn(product.name, message)
        self.assert_nothing_was_created_or_moved()

    def test_draft_from_another_company_is_not_restored(self):
        other_company = make_company(name="Empresa antiga")
        session = self.client.session
        session[PDV_DRAFT_SESSION_KEY] = {
            "company_id": other_company.pk,
            "table_or_tab": "Comanda antiga",
            "cart": [
                {
                    "id": "999",
                    "name": "Produto secreto antigo",
                    "price": "1.00",
                    "quantity": 1,
                }
            ],
        }
        session.save()

        response = self.client.get(reverse("orders:pdv"))

        self.assertEqual(response.context["initial_cart"], [])
        self.assertEqual(response.context["initial_table_or_tab"], "")
        self.assertNotContains(response, "Produto secreto antigo")
        self.assertNotContains(response, "Comanda antiga")

    def test_successful_post_clears_an_old_draft(self):
        product = self.make_product(name="Produto válido")
        make_entry(product=product, quantity="5.00")
        session = self.client.session
        session[PDV_DRAFT_SESSION_KEY] = {
            "company_id": self.company.pk,
            "table_or_tab": "Comanda velha",
            "cart": [],
        }
        session.save()

        self.post_cart([{"id": product.pk, "quantity": 1}])

        self.assertNotIn(PDV_DRAFT_SESSION_KEY, self.client.session)
        self.assertEqual(Order.objects.count(), 1)

    def test_approval_revalidates_after_stock_is_consumed(self):
        product = self.make_product(name="Estoque disputado")
        entry = make_entry(product=product, quantity="5.00")

        _response, _message = self.post_cart(
            [{"id": product.pk, "quantity": 5}]
        )
        pending_order = Order.objects.get()

        competing_order, _items = make_order(
            company=self.company,
            created_by=self.user,
            lines=[(product, "5.00", "10.00")],
        )
        approve_order(
            order_id=competing_order.pk,
            company=self.company,
            payment_method="pix",
            user=self.user,
        )

        with self.assertRaises(InsufficientStock):
            approve_order(
                order_id=pending_order.pk,
                company=self.company,
                payment_method="pix",
                user=self.user,
            )

        pending_order.refresh_from_db()
        entry.refresh_from_db()
        self.assertEqual(pending_order.status, "pre_sale")
        self.assertIsNone(pending_order.sale_id)
        self.assertEqual(entry.remaining_quantity, 0)
        self.assertEqual(Sale.objects.count(), 1)
        self.assertEqual(
            StockMovement.objects.filter(movement_type="sale").count(),
            1,
        )
