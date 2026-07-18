from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from orders.models import Order, OrderItem
from orders.services import (
    InvalidOrderState,
    cancel_pre_sale_order,
    discard_paid_order,
    mark_order_delivered,
)
from sales.models import Sale

from .helpers import OrderTestMixin


D = Decimal


class OrderStateServiceTests(OrderTestMixin, TestCase):
    def test_mark_delivered_service_and_wrapper_are_idempotent(self):
        order = Order.objects.create(company=self.company, status="sold")
        stale = Order.objects.get(pk=order.pk)

        first = mark_order_delivered(
            order_id=order.pk,
            company=self.company,
        )
        wrapper_return = stale.mark_delivered()

        order.refresh_from_db()
        self.assertTrue(first.changed)
        self.assertIsNone(wrapper_return)
        self.assertEqual(order.status, "delivered")
        self.assertIsNotNone(order.delivered_at)

    def test_cancel_pre_sale_service_and_wrapper_are_idempotent(self):
        order = Order.objects.create(company=self.company)
        stale = Order.objects.get(pk=order.pk)

        first = cancel_pre_sale_order(
            order_id=order.pk,
            company=self.company,
        )
        wrapper_return = stale.cancel()

        order.refresh_from_db()
        self.assertTrue(first.changed)
        self.assertIsNone(wrapper_return)
        self.assertEqual(order.status, "cancelled")

    def test_discard_service_updates_sale_and_wrapper_keeps_none_return(self):
        sale = Sale.objects.create(
            company=self.company,
            payment_method="pix",
            created_by=self.user,
        )
        order = Order.objects.create(
            company=self.company,
            status="sold",
            sale=sale,
        )
        stale = Order.objects.get(pk=order.pk)

        result = discard_paid_order(
            order_id=order.pk,
            company=self.company,
            user=self.user,
        )
        wrapper_return = stale.discard_paid_order(user=self.user)

        order.refresh_from_db()
        sale.refresh_from_db()
        self.assertTrue(result.changed)
        self.assertIsNone(wrapper_return)
        self.assertEqual(order.status, "discarded")
        self.assertEqual(sale.status, "discarded")

    def test_cancelled_order_without_sale_is_not_paid_cancel_idempotency(self):
        order = Order.objects.create(
            company=self.company,
            status="cancelled",
        )

        with self.assertRaisesMessage(
            InvalidOrderState,
            "não possui uma venda vinculada",
        ):
            order.cancel_paid_and_return_stock(user=self.user)


class OrderItemStateTests(OrderTestMixin, TestCase):
    def test_product_price_is_defaulted_only_when_item_is_created(self):
        product = self.make_product(sale_price="17.50")
        order, items = self.make_order([(product, "2.00")])
        item = items[0]

        self.assertEqual(item.unit_price, D("17.50"))

        item.unit_price = D("0.00")
        item.save()

        item.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(item.unit_price, D("0.00"))
        self.assertEqual(item.total_price, D("0.00"))
        self.assertEqual(order.total_amount, D("0.00"))

    def test_item_can_be_deleted_while_order_is_pre_sale(self):
        product = self.make_product(sale_price="12.00")
        order, items = self.make_order([(product, "2.00", "12.00")])
        item = items[0]

        deleted_count, _details = item.delete()

        order.refresh_from_db()
        self.assertEqual(deleted_count, 1)
        self.assertEqual(order.total_amount, D("0.00"))
        self.assertFalse(OrderItem.objects.filter(order=order).exists())

    def test_item_cannot_be_created_after_order_is_sold(self):
        product = self.make_product()
        order = Order.objects.create(company=self.company, status="sold")

        with self.assertRaisesMessage(ValidationError, "pré-venda"):
            OrderItem.objects.create(
                order=order,
                company=self.company,
                product=product,
                quantity=D("1.00"),
            )

        self.assertFalse(OrderItem.objects.filter(order=order).exists())

    def test_item_cannot_be_edited_after_order_is_sold(self):
        product = self.make_product()
        order, items = self.make_order([(product, "1.00", "10.00")])
        item = items[0]
        Order.objects.filter(pk=order.pk).update(status="sold")

        item.quantity = D("5.00")
        with self.assertRaisesMessage(ValidationError, "pré-venda"):
            item.save()

        item.refresh_from_db()
        self.assertEqual(item.quantity, D("1.00"))

    def test_item_cannot_be_deleted_after_order_is_sold(self):
        product = self.make_product()
        order, items = self.make_order([(product, "1.00", "10.00")])
        item = items[0]
        Order.objects.filter(pk=order.pk).update(status="sold")

        with self.assertRaisesMessage(ValidationError, "pré-venda"):
            item.delete()

        self.assertTrue(OrderItem.objects.filter(pk=item.pk).exists())

