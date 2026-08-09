from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from orders import services as order_services
from orders.models import Order, OrderItem
from orders.services import InvalidOrderData, InvalidOrderState, approve_order
from products.models import StockEntry, StockMovement
from products.services import InsufficientStock
from sales.models import Sale, SaleItem

from .helpers import (
    OrderTestMixin,
    fifo_times,
    make_company,
    make_entry,
    make_product,
    make_unit,
)


D = Decimal


class ApprovalServiceTests(OrderTestMixin, TestCase):
    def assert_approval_was_not_persisted(self, order):
        order.refresh_from_db()
        self.assertEqual(order.status, "pre_sale")
        self.assertIsNone(order.sale_id)
        self.assertIsNone(order.approved_by_id)
        self.assertIsNone(order.approved_at)
        self.assertEqual(Sale.objects.count(), 0)
        self.assertEqual(SaleItem.objects.count(), 0)
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_approval_consumes_one_entry(self):
        product = self.make_product(sale_price="10.00")
        entry = make_entry(
            product=product,
            quantity="10.00",
            total_cost="20.00",
        )
        order, order_items = self.make_order([(product, "3.00", "10.00")])

        result = approve_order(
            order_id=order.pk,
            company=self.company,
            payment_method="pix",
            user=self.user,
        )

        self.assertTrue(result.created)
        order.refresh_from_db()
        entry.refresh_from_db()
        result.sale.refresh_from_db()
        sale_item = result.sale.items.get()
        movement = StockMovement.objects.get(movement_type="sale")

        self.assertEqual(entry.remaining_quantity, D("7.00"))
        self.assertEqual(order.status, "sold")
        self.assertEqual(order.sale_id, result.sale.pk)
        self.assertEqual(order.approved_by_id, self.user.pk)
        self.assertIsNotNone(order.approved_at)
        self.assertEqual(Sale.objects.count(), 1)
        self.assertEqual(SaleItem.objects.count(), 1)
        self.assertEqual(sale_item.quantity, D("3.00"))
        self.assertEqual(sale_item.unit_price, order_items[0].unit_price)
        self.assertEqual(sale_item.total_price, D("30.00"))
        self.assertEqual(sale_item.unit_cost, D("2.00"))
        self.assertEqual(sale_item.total_cost, D("6.00"))
        self.assertEqual(result.sale.total_amount, D("30.00"))
        self.assertEqual(result.sale.total_cost, D("6.00"))
        self.assertEqual(result.sale.gross_profit, D("24.00"))
        self.assertEqual(movement.company_id, self.company.pk)
        self.assertEqual(movement.product_id, product.pk)
        self.assertEqual(movement.stock_entry_id, entry.pk)
        self.assertEqual(movement.sale_item_id, sale_item.pk)
        self.assertEqual(movement.quantity, D("3.00"))
        self.assertEqual(movement.sale_value, D("30.00"))
        self.assertEqual(movement.cost_value, D("6.00"))

    def test_approval_consumes_two_entries_fifo_and_uses_allocation_cost(self):
        product = self.make_product(sale_price="10.00")
        older_time, newer_time = fifo_times()
        older = make_entry(
            product=product,
            quantity="2.00",
            total_cost="4.00",
            created_at=older_time,
        )
        newer = make_entry(
            product=product,
            quantity="8.00",
            total_cost="32.00",
            created_at=newer_time,
        )
        order, _items = self.make_order([(product, "5.00", "10.00")])

        result = approve_order(
            order_id=order.pk,
            company=self.company,
            payment_method="cash",
            user=self.user,
        )

        older.refresh_from_db()
        newer.refresh_from_db()
        sale_item = result.sale.items.get()
        sale_item.refresh_from_db()
        result.sale.refresh_from_db()
        movements = list(
            StockMovement.objects.filter(
                movement_type="sale",
                sale_item=sale_item,
            ).order_by("stock_entry_id")
        )
        movement_by_entry = {movement.stock_entry_id: movement for movement in movements}

        self.assertEqual(older.remaining_quantity, D("0.00"))
        self.assertEqual(newer.remaining_quantity, D("5.00"))
        self.assertEqual(len(movements), 2)
        self.assertEqual(movement_by_entry[older.pk].quantity, D("2.00"))
        self.assertEqual(movement_by_entry[newer.pk].quantity, D("3.00"))
        self.assertEqual(
            sum((movement.quantity for movement in movements), D("0.00")),
            D("5.00"),
        )
        self.assertFalse(
            product.stock_entries.filter(remaining_quantity__lt=0).exists()
        )
        # FIFO cost is 2 * R$2 + 3 * R$4 = R$16, not the stock average.
        self.assertEqual(sale_item.total_cost, D("16.00"))
        self.assertEqual(sale_item.unit_cost, D("3.20"))
        self.assertEqual(result.sale.total_cost, D("16.00"))
        self.assertEqual(result.sale.gross_profit, D("34.00"))

    def test_fifo_uses_entry_id_when_created_at_is_equal(self):
        product = self.make_product()
        first = make_entry(product=product, quantity="1.00")
        second = make_entry(product=product, quantity="1.00")
        same_time, _unused = fifo_times()
        product.stock_entries.filter(pk__in=[first.pk, second.pk]).update(
            created_at=same_time
        )
        order, _items = self.make_order([(product, "1.00", "10.00")])

        approve_order(
            order_id=order.pk,
            company=self.company,
            payment_method="pix",
            user=self.user,
        )

        first.refresh_from_db()
        second.refresh_from_db()
        movement = StockMovement.objects.get(movement_type="sale")
        self.assertLess(first.pk, second.pk)
        self.assertEqual(first.remaining_quantity, D("0.00"))
        self.assertEqual(second.remaining_quantity, D("1.00"))
        self.assertEqual(movement.stock_entry_id, first.pk)

    def test_insufficient_stock_leaves_everything_unchanged(self):
        product = self.make_product()
        entry = make_entry(product=product, quantity="4.00")
        order, _items = self.make_order([(product, "5.00", "10.00")])

        with self.assertRaises(InsufficientStock):
            approve_order(
                order_id=order.pk,
                company=self.company,
                payment_method="pix",
                user=self.user,
            )

        entry.refresh_from_db()
        self.assertEqual(entry.remaining_quantity, D("4.00"))
        self.assert_approval_was_not_persisted(order)

    def test_second_item_without_stock_rolls_back_entire_approval(self):
        first_product = self.make_product(name="Primeiro")
        second_product = self.make_product(name="Segundo")
        first_entry = make_entry(product=first_product, quantity="5.00")
        second_entry = make_entry(product=second_product, quantity="1.00")
        order, _items = self.make_order(
            [
                (first_product, "2.00", "10.00"),
                (second_product, "2.00", "10.00"),
            ]
        )

        with self.assertRaises(InsufficientStock):
            approve_order(
                order_id=order.pk,
                company=self.company,
                payment_method="pix",
                user=self.user,
            )

        first_entry.refresh_from_db()
        second_entry.refresh_from_db()
        self.assertEqual(first_entry.remaining_quantity, D("5.00"))
        self.assertEqual(second_entry.remaining_quantity, D("1.00"))
        self.assert_approval_was_not_persisted(order)

    def test_unexpected_failure_on_second_consumption_rolls_back_first(self):
        first_product = self.make_product(name="Primeiro")
        second_product = self.make_product(name="Segundo")
        first_entry = make_entry(product=first_product, quantity="5.00")
        second_entry = make_entry(product=second_product, quantity="5.00")
        order, _items = self.make_order(
            [
                (first_product, "2.00", "10.00"),
                (second_product, "2.00", "10.00"),
            ]
        )
        real_consume_stock = order_services.consume_stock
        calls = 0

        def consume_then_fail(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("falha injetada no segundo item")
            return real_consume_stock(**kwargs)

        with patch(
            "orders.services.consume_stock",
            side_effect=consume_then_fail,
        ):
            with self.assertRaisesRegex(RuntimeError, "falha injetada"):
                approve_order(
                    order_id=order.pk,
                    company=self.company,
                    payment_method="pix",
                    user=self.user,
                )

        first_entry.refresh_from_db()
        second_entry.refresh_from_db()
        self.assertEqual(first_entry.remaining_quantity, D("5.00"))
        self.assertEqual(second_entry.remaining_quantity, D("5.00"))
        self.assert_approval_was_not_persisted(order)

    def test_duplicate_sequential_approval_is_idempotent(self):
        product = self.make_product()
        entry = make_entry(product=product, quantity="10.00")
        order, _items = self.make_order([(product, "3.00", "10.00")])

        first_result = approve_order(
            order_id=order.pk,
            company=self.company,
            payment_method="pix",
            user=self.user,
        )
        second_result = approve_order(
            order_id=order.pk,
            company=self.company,
            payment_method="pix",
            user=self.user,
        )

        entry.refresh_from_db()
        self.assertTrue(first_result.created)
        self.assertFalse(second_result.created)
        self.assertEqual(first_result.sale.pk, second_result.sale.pk)
        self.assertEqual(entry.remaining_quantity, D("7.00"))
        self.assertEqual(Sale.objects.count(), 1)
        self.assertEqual(SaleItem.objects.count(), 1)
        self.assertEqual(
            StockMovement.objects.filter(movement_type="sale").count(),
            1,
        )

    def test_legacy_approved_order_is_reported_instead_of_silently_accepted(self):
        product = self.make_product()
        entry = make_entry(product=product, quantity="10.00")
        order, _items = self.make_order([(product, "3.00", "10.00")])
        approve_order(
            order_id=order.pk,
            company=self.company,
            payment_method="pix",
            user=self.user,
        )
        StockMovement.objects.filter(movement_type="sale").update(sale_item=None)

        with self.assertRaisesMessage(InvalidOrderState, "legada"):
            approve_order(
                order_id=order.pk,
                company=self.company,
                payment_method="pix",
                user=self.user,
            )

        entry.refresh_from_db()
        self.assertEqual(entry.remaining_quantity, D("7.00"))
        self.assertEqual(Sale.objects.count(), 1)
        self.assertEqual(SaleItem.objects.count(), 1)
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_stale_order_instances_cannot_duplicate_approval(self):
        product = self.make_product()
        entry = make_entry(product=product, quantity="10.00")
        order, _items = self.make_order([(product, "3.00", "10.00")])
        stale_first = Order.objects.get(pk=order.pk)
        stale_second = Order.objects.get(pk=order.pk)

        first_sale = stale_first.approve(payment_method="pix", user=self.user)
        second_sale = stale_second.approve(payment_method="pix", user=self.user)

        entry.refresh_from_db()
        self.assertEqual(first_sale.pk, second_sale.pk)
        self.assertEqual(entry.remaining_quantity, D("7.00"))
        self.assertEqual(Sale.objects.count(), 1)
        self.assertEqual(SaleItem.objects.count(), 1)
        self.assertEqual(
            StockMovement.objects.filter(movement_type="sale").count(),
            1,
        )

    def test_repeated_product_lines_are_aggregated_before_validation(self):
        product = self.make_product()
        entry = make_entry(product=product, quantity="5.00")
        order, _items = self.make_order(
            [
                (product, "3.00", "10.00"),
                (product, "3.00", "10.00"),
            ]
        )

        with self.assertRaises(InsufficientStock) as error:
            approve_order(
                order_id=order.pk,
                company=self.company,
                payment_method="pix",
                user=self.user,
            )

        entry.refresh_from_db()
        self.assertEqual(error.exception.requested, D("6.00"))
        self.assertEqual(entry.remaining_quantity, D("5.00"))
        self.assert_approval_was_not_persisted(order)

    def test_approval_preserves_order_item_price_after_product_price_change(self):
        product = self.make_product(sale_price="12.50")
        make_entry(product=product, quantity="10.00")
        order, order_items = self.make_order([(product, "2.00")])
        agreed_price = order_items[0].unit_price
        product.sale_price = D("99.90")
        product.save(update_fields=["sale_price"])

        result = approve_order(
            order_id=order.pk,
            company=self.company,
            payment_method="credit",
            user=self.user,
        )

        sale_item = result.sale.items.get()
        result.sale.refresh_from_db()
        self.assertEqual(agreed_price, D("12.50"))
        self.assertEqual(sale_item.unit_price, agreed_price)
        self.assertEqual(sale_item.total_price, D("25.00"))
        self.assertEqual(result.sale.total_amount, D("25.00"))

    def test_product_from_another_company_is_rejected_without_partial_records(self):
        other_company = make_company(name="Outra empresa")
        other_unit = make_unit(company=other_company)
        foreign_product = make_product(
            company=other_company,
            unit=other_unit,
            sale_price="10.00",
        )
        foreign_entry = make_entry(product=foreign_product, quantity="5.00")
        order, _items = self.make_order([])
        # bulk_create deliberately bypasses OrderItem.save() to simulate corrupt data.
        OrderItem.objects.bulk_create(
            [
                OrderItem(
                    order=order,
                    company=self.company,
                    product=foreign_product,
                    quantity=D("1.00"),
                    unit_price=D("10.00"),
                    total_price=D("10.00"),
                )
            ]
        )

        with self.assertRaises(InvalidOrderData):
            approve_order(
                order_id=order.pk,
                company=self.company,
                payment_method="pix",
                user=self.user,
            )

        foreign_entry.refresh_from_db()
        self.assertEqual(foreign_entry.remaining_quantity, D("5.00"))
        self.assert_approval_was_not_persisted(order)

    def test_entry_from_another_company_is_never_consumed(self):
        other_company = make_company(name="Outra empresa")
        product = self.make_product()
        foreign_entry = make_entry(product=product, quantity="5.00")
        # Simula um registro legado inconsistente sem enfraquecer a validação atual.
        StockEntry.objects.filter(pk=foreign_entry.pk).update(
            company=other_company
        )
        foreign_entry.refresh_from_db()
        order, _items = self.make_order([(product, "1.00", "10.00")])

        with self.assertRaises(InsufficientStock):
            approve_order(
                order_id=order.pk,
                company=self.company,
                payment_method="pix",
                user=self.user,
            )

        foreign_entry.refresh_from_db()
        self.assertEqual(foreign_entry.remaining_quantity, D("5.00"))
        self.assert_approval_was_not_persisted(order)

    def test_order_cannot_be_approved_through_another_company_context(self):
        other_company = make_company(name="Outra empresa")
        product = self.make_product()
        entry = make_entry(product=product, quantity="5.00")
        order, _items = self.make_order([(product, "1.00", "10.00")])

        with self.assertRaises(Order.DoesNotExist):
            approve_order(
                order_id=order.pk,
                company=other_company,
                payment_method="pix",
                user=self.user,
            )

        entry.refresh_from_db()
        self.assertEqual(entry.remaining_quantity, D("5.00"))
        self.assert_approval_was_not_persisted(order)
