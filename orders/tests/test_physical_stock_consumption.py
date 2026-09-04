from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from orders.services import approve_order, cancel_paid_order_with_stock_return
from products.models import StockMovement
from products.sale_quantities import get_sale_availability
from products.services import InsufficientStock
from sales.models import Sale, SaleItem

from .helpers import OrderTestMixin, fifo_times, make_entry


D = Decimal


class PhysicalStockApprovalTests(OrderTestMixin, TestCase):
    def dose_product(self, **overrides):
        values = {
            "sale_form": "dose",
            "stock_dimension": "volume",
            "dose_ml": "50",
            "sale_price": "10.00",
        }
        values.update(overrides)
        return self.make_product(**values)

    def portion_product(self, **overrides):
        values = {
            "sale_form": "portion",
            "stock_dimension": "weight",
            "portion_g": "400",
            "sale_price": "20.00",
        }
        values.update(overrides)
        return self.make_product(**values)

    def assert_approval_rolled_back(self, order):
        order.refresh_from_db()
        self.assertEqual(order.status, "pre_sale")
        self.assertIsNone(order.sale_id)
        self.assertFalse(Sale.objects.exists())
        self.assertFalse(SaleItem.objects.exists())
        self.assertFalse(StockMovement.objects.exists())

    def test_two_doses_consume_100_ml_and_persist_conversion_snapshot(self):
        product = self.dose_product()
        entry = make_entry(product=product, quantity="1000", total_cost="100")
        order, _items = self.make_order([(product, "2", "10")])

        result = approve_order(
            order_id=order.pk,
            company=self.company,
            payment_method="pix",
            user=self.user,
        )

        entry.refresh_from_db()
        sale_item = result.sale.items.get()
        movement = StockMovement.objects.get(movement_type="sale")
        self.assertEqual(entry.remaining_quantity, D("900"))
        self.assertEqual(sale_item.quantity, D("2"))
        self.assertEqual(sale_item.sale_form_snapshot, "dose")
        self.assertEqual(sale_item.physical_quantity_per_sale_unit, D("50"))
        self.assertEqual(sale_item.physical_quantity_total, D("100"))
        self.assertEqual(sale_item.physical_base_unit, "mL")
        self.assertEqual(movement.quantity, D("100"))
        self.assertEqual(movement.sale_value, D("20"))
        self.assertEqual(sale_item.total_cost, D("10"))

    def test_multiple_fifo_lots_split_physical_dose_and_sale_value(self):
        product = self.dose_product()
        older_time, newer_time = fifo_times()
        older = make_entry(
            product=product,
            quantity="60",
            total_cost="6",
            created_at=older_time,
        )
        newer = make_entry(
            product=product,
            quantity="100",
            total_cost="20",
            created_at=newer_time,
        )
        order, _items = self.make_order([(product, "2", "10")])

        result = approve_order(
            order_id=order.pk,
            company=self.company,
            payment_method="cash",
            user=self.user,
        )

        older.refresh_from_db()
        newer.refresh_from_db()
        movements = list(
            result.sale.items.get().stock_movements.order_by("stock_entry_id")
        )
        movement_by_entry = {
            movement.stock_entry_id: movement for movement in movements
        }
        self.assertEqual(older.remaining_quantity, D("0"))
        self.assertEqual(newer.remaining_quantity, D("60"))
        self.assertEqual(movement_by_entry[older.pk].quantity, D("60"))
        self.assertEqual(movement_by_entry[newer.pk].quantity, D("40"))
        self.assertEqual(movement_by_entry[older.pk].sale_value, D("12"))
        self.assertEqual(movement_by_entry[newer.pk].sale_value, D("8"))

    def test_three_portions_consume_1200_grams(self):
        product = self.portion_product()
        entry = make_entry(product=product, quantity="5000", total_cost="50")
        order, _items = self.make_order([(product, "3", "20")])

        result = approve_order(
            order_id=order.pk,
            company=self.company,
            payment_method="debit",
            user=self.user,
        )

        entry.refresh_from_db()
        sale_item = result.sale.items.get()
        self.assertEqual(entry.remaining_quantity, D("3800"))
        self.assertEqual(sale_item.physical_quantity_total, D("1200"))
        self.assertEqual(sale_item.physical_base_unit, "g")

    def test_changing_dose_recalculates_availability_without_changing_stock(self):
        product = self.dose_product(dose_ml="50")
        make_entry(product=product, quantity="4500")

        before = get_sale_availability(product)
        product.dose_ml = D("100")
        product.save(update_fields=["dose_ml"])
        product.refresh_from_db()
        after = get_sale_availability(product)

        self.assertEqual(product.current_stock, D("4500"))
        self.assertEqual(before.available_sale_quantity, D("90"))
        self.assertEqual(after.available_sale_quantity, D("45"))

    def test_cancellation_restores_original_100_ml_after_dose_changes(self):
        product = self.dose_product(dose_ml="50")
        entry = make_entry(product=product, quantity="1000")
        order, _items = self.make_order([(product, "2", "10")])
        approval = approve_order(
            order_id=order.pk,
            company=self.company,
            payment_method="pix",
            user=self.user,
        )
        product.dose_ml = D("100")
        product.save(update_fields=["dose_ml"])

        cancel_paid_order_with_stock_return(
            order_id=order.pk,
            company=self.company,
            user=self.user,
        )

        entry.refresh_from_db()
        sale_item = approval.sale.items.get()
        outbound = StockMovement.objects.get(movement_type="sale")
        returned = StockMovement.objects.get(movement_type="return_to_stock")
        self.assertEqual(entry.remaining_quantity, D("1000"))
        self.assertEqual(sale_item.physical_quantity_per_sale_unit, D("50"))
        self.assertEqual(sale_item.physical_quantity_total, D("100"))
        self.assertEqual(outbound.quantity, D("100"))
        self.assertEqual(returned.quantity, D("100"))

    def test_persisted_physical_snapshot_is_immutable(self):
        product = self.dose_product(dose_ml="50")
        make_entry(product=product, quantity="1000")
        order, _items = self.make_order([(product, "2", "10")])
        approval = approve_order(
            order_id=order.pk,
            company=self.company,
            payment_method="pix",
            user=self.user,
        )
        sale_item = approval.sale.items.get()

        sale_item.physical_quantity_per_sale_unit = D("100")
        sale_item.physical_quantity_total = D("200")

        with self.assertRaisesMessage(ValidationError, "não pode ser alterado"):
            sale_item.save()

        sale_item.refresh_from_db()
        self.assertEqual(sale_item.physical_quantity_per_sale_unit, D("50"))
        self.assertEqual(sale_item.physical_quantity_total, D("100"))

    def test_insufficient_physical_stock_rolls_back_without_partial_sale(self):
        product = self.dose_product()
        entry = make_entry(product=product, quantity="99")
        order, _items = self.make_order([(product, "2", "10")])

        with self.assertRaises(InsufficientStock) as error:
            approve_order(
                order_id=order.pk,
                company=self.company,
                payment_method="pix",
                user=self.user,
            )

        entry.refresh_from_db()
        self.assertEqual(error.exception.requested, D("100"))
        self.assertEqual(entry.remaining_quantity, D("99"))
        self.assert_approval_rolled_back(order)

    def test_second_physical_item_failure_rolls_back_every_item_atomically(self):
        dose = self.dose_product(name="Dose")
        portion = self.portion_product(name="Porção")
        dose_entry = make_entry(product=dose, quantity="500")
        portion_entry = make_entry(product=portion, quantity="399")
        order, _items = self.make_order(
            [(dose, "2", "10"), (portion, "1", "20")]
        )

        with self.assertRaises(InsufficientStock):
            approve_order(
                order_id=order.pk,
                company=self.company,
                payment_method="pix",
                user=self.user,
            )

        dose_entry.refresh_from_db()
        portion_entry.refresh_from_db()
        self.assertEqual(dose_entry.remaining_quantity, D("500"))
        self.assertEqual(portion_entry.remaining_quantity, D("399"))
        self.assert_approval_rolled_back(order)

    def test_pre_portioned_product_consumes_only_its_own_stock(self):
        product = self.portion_product(
            name="Porção pronta",
            inventory_role="prepared",
            preparation_mode="pre_portioned",
        )
        entry = make_entry(product=product, quantity="800")
        order, _items = self.make_order([(product, "1", "20")])

        approve_order(
            order_id=order.pk,
            company=self.company,
            payment_method="pix",
            user=self.user,
        )

        entry.refresh_from_db()
        self.assertEqual(entry.remaining_quantity, D("400"))
        self.assertEqual(StockMovement.objects.filter(movement_type="sale").count(), 1)
