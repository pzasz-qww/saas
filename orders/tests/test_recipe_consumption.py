from decimal import Decimal
from unittest.mock import patch

from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from orders.services import (
    approve_order,
    cancel_paid_order_with_stock_return,
    discard_paid_order,
)
from products.models import ProductComponent, StockMovement
from products.recipe_services import InvalidOperationalRecipe
from products.services import InsufficientStock
from sales.models import Sale, SaleItem, SaleItemComponent

from .helpers import (
    OrderTestMixin,
    fifo_times,
    make_company,
    make_entry,
    make_product,
    make_unit,
)


D = Decimal


class RecipeConsumptionTests(OrderTestMixin, TestCase):
    def prepared(self, name="Caipirinha", **overrides):
        values = {
            "name": name,
            "inventory_role": "prepared",
            "preparation_mode": "on_demand",
            "sale_price": "20",
        }
        values.update(overrides)
        return self.make_product(**values)

    def ingredient(self, name, dimension="count", **overrides):
        values = {
            "name": name,
            "inventory_role": "input",
            "product_type": "internal_use",
            "stock_dimension": dimension,
        }
        values.update(overrides)
        return self.make_product(**values)

    def component(self, product, ingredient, quantity, unit):
        return ProductComponent.objects.create(
            company=self.company,
            product=product,
            ingredient=ingredient,
            quantity=D(quantity),
            unit=unit,
        )

    def approve(self, order):
        return approve_order(
            order_id=order.pk,
            company=self.company,
            payment_method="pix",
            user=self.user,
        )

    def assert_approval_rolled_back(self, order, entries):
        order.refresh_from_db()
        self.assertEqual(order.status, "pre_sale")
        self.assertIsNone(order.sale_id)
        self.assertFalse(Sale.objects.exists())
        self.assertFalse(SaleItem.objects.exists())
        self.assertFalse(SaleItemComponent.objects.exists())
        self.assertFalse(StockMovement.objects.exists())
        for entry, expected in entries:
            entry.refresh_from_db()
            self.assertEqual(entry.remaining_quantity, D(expected))

    def test_on_demand_sale_consumes_every_registered_ingredient_without_own_lot(self):
        drink = self.prepared()
        spirit = self.ingredient("Cachaça", "volume")
        lemon = self.ingredient("Limão", "weight")
        sugar = self.ingredient("Açúcar", "weight")
        cup = self.ingredient("Copo")
        self.component(drink, spirit, "50", "mL")
        self.component(drink, lemon, "80", "g")
        self.component(drink, sugar, "15", "g")
        self.component(drink, cup, "1", "unit")
        entries = {
            spirit: make_entry(product=spirit, quantity="500", total_cost="16"),
            lemon: make_entry(product=lemon, quantity="800", total_cost="5.50"),
            sugar: make_entry(product=sugar, quantity="150", total_cost="0.75"),
            cup: make_entry(product=cup, quantity="10", total_cost="2"),
        }
        order, _items = self.make_order([(drink, "2", "20")])

        result = self.approve(order)

        expected_remaining = {
            spirit: D("400"),
            lemon: D("640"),
            sugar: D("120"),
            cup: D("8"),
        }
        for ingredient, entry in entries.items():
            entry.refresh_from_db()
            self.assertEqual(entry.remaining_quantity, expected_remaining[ingredient])
        self.assertFalse(drink.stock_entries.exists())
        sale_item = result.sale.items.get()
        sale_item.refresh_from_db()
        result.sale.refresh_from_db()
        self.assertEqual(sale_item.total_cost, D("4.85"))
        self.assertEqual(result.sale.total_cost, D("4.85"))
        snapshots = {
            snapshot.ingredient: snapshot
            for snapshot in sale_item.component_snapshots.all()
        }
        self.assertEqual(set(snapshots), set(entries))
        self.assertEqual(snapshots[spirit].quantity_per_sale_unit, D("50"))
        self.assertEqual(snapshots[spirit].physical_quantity_total, D("100"))
        self.assertEqual(
            StockMovement.objects.filter(
                sale_item=sale_item,
                movement_type="sale",
            ).count(),
            4,
        )
        for movement in StockMovement.objects.filter(sale_item=sale_item):
            self.assertEqual(
                movement.product_id,
                movement.sale_item_component.ingredient_id,
            )
            self.assertEqual(
                movement.stock_entry.product_id,
                movement.product_id,
            )

    def test_component_crosses_fifo_lots_and_cost_uses_real_allocations(self):
        drink = self.prepared(sale_price="30")
        spirit = self.ingredient("Cachaça", "volume")
        self.component(drink, spirit, "50", "mL")
        older_time, newer_time = fifo_times()
        older = make_entry(
            product=spirit,
            quantity="100",
            total_cost="20",
            created_at=older_time,
        )
        newer = make_entry(
            product=spirit,
            quantity="100",
            total_cost="40",
            created_at=newer_time,
        )
        order, _items = self.make_order([(drink, "3", "30")])

        result = self.approve(order)

        older.refresh_from_db()
        newer.refresh_from_db()
        sale_item = result.sale.items.get()
        sale_item.refresh_from_db()
        movements = list(
            StockMovement.objects.filter(
                sale_item=sale_item,
                movement_type="sale",
            ).order_by("stock_entry_id")
        )
        self.assertEqual(older.remaining_quantity, D("0"))
        self.assertEqual(newer.remaining_quantity, D("50"))
        self.assertEqual([movement.quantity for movement in movements], [D("100"), D("50")])
        self.assertEqual(sum((movement.cost_value for movement in movements), D("0")), D("40"))
        self.assertEqual(sale_item.total_cost, D("40"))
        self.assertEqual(result.sale.total_cost, D("40"))

    def test_shared_ingredient_is_aggregated_before_any_stock_change(self):
        first = self.prepared("Caipirinha")
        second = self.prepared("Batida")
        spirit = self.ingredient("Cachaça", "volume")
        self.component(first, spirit, "100", "mL")
        self.component(second, spirit, "80", "mL")
        entry = make_entry(product=spirit, quantity="150")
        order, _items = self.make_order(
            [(first, "1", "20"), (second, "1", "20")]
        )

        with self.assertRaises(InsufficientStock) as error:
            self.approve(order)

        self.assertEqual(error.exception.requested, D("180"))
        self.assert_approval_rolled_back(order, [(entry, "150")])

    def test_one_insufficient_component_rolls_back_all_ingredients(self):
        drink = self.prepared()
        spirit = self.ingredient("Cachaça", "volume")
        lemon = self.ingredient("Limão", "weight")
        self.component(drink, spirit, "50", "mL")
        self.component(drink, lemon, "80", "g")
        spirit_entry = make_entry(product=spirit, quantity="500")
        lemon_entry = make_entry(product=lemon, quantity="159")
        order, _items = self.make_order([(drink, "2", "20")])

        with self.assertRaises(InsufficientStock):
            self.approve(order)

        self.assert_approval_rolled_back(
            order,
            [(spirit_entry, "500"), (lemon_entry, "159")],
        )

    def test_unexpected_failure_on_second_component_rolls_back_first(self):
        drink = self.prepared()
        spirit = self.ingredient("Cachaça", "volume")
        lemon = self.ingredient("Limão", "weight")
        self.component(drink, spirit, "50", "mL")
        self.component(drink, lemon, "80", "g")
        spirit_entry = make_entry(product=spirit, quantity="500")
        lemon_entry = make_entry(product=lemon, quantity="800")
        order, _items = self.make_order([(drink, "2", "20")])

        from orders import services as order_services

        real_consume = order_services.consume_component_stock
        calls = 0

        def consume_then_fail(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("falha injetada no segundo componente")
            return real_consume(**kwargs)

        with patch(
            "orders.services.consume_component_stock",
            side_effect=consume_then_fail,
        ):
            with self.assertRaisesRegex(RuntimeError, "segundo componente"):
                self.approve(order)

        self.assert_approval_rolled_back(
            order,
            [(spirit_entry, "500"), (lemon_entry, "800")],
        )

    def test_recipe_snapshot_does_not_change_after_component_is_edited(self):
        drink = self.prepared()
        spirit = self.ingredient("Cachaça", "volume")
        component = self.component(drink, spirit, "50", "mL")
        make_entry(product=spirit, quantity="500")
        order, _items = self.make_order([(drink, "2", "20")])
        approval = self.approve(order)

        component.quantity = D("60")
        component.unit = "mL"
        component.save()

        snapshot = approval.sale.items.get().component_snapshots.get()
        self.assertEqual(snapshot.quantity_per_sale_unit, D("50"))
        self.assertEqual(snapshot.physical_quantity_total, D("100"))
        self.assertEqual(
            StockMovement.objects.get(movement_type="sale").quantity,
            D("100"),
        )

    def test_duplicate_approval_does_not_consume_recipe_twice(self):
        drink = self.prepared()
        spirit = self.ingredient("Cachaça", "volume")
        self.component(drink, spirit, "50", "mL")
        entry = make_entry(product=spirit, quantity="500")
        order, _items = self.make_order([(drink, "2", "20")])

        first = self.approve(order)
        second = self.approve(order)

        entry.refresh_from_db()
        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(first.sale.pk, second.sale.pk)
        self.assertEqual(entry.remaining_quantity, D("400"))
        self.assertEqual(SaleItemComponent.objects.count(), 1)
        self.assertEqual(StockMovement.objects.filter(movement_type="sale").count(), 1)

    def test_recipe_snapshot_fields_cannot_be_edited(self):
        drink = self.prepared()
        spirit = self.ingredient("Cachaça", "volume")
        self.component(drink, spirit, "50", "mL")
        make_entry(product=spirit, quantity="500")
        order, _items = self.make_order([(drink, "2", "20")])
        approval = self.approve(order)
        snapshot = approval.sale.items.get().component_snapshots.get()

        snapshot.quantity_per_sale_unit = D("60")
        snapshot.physical_quantity_total = D("120")

        from django.core.exceptions import ValidationError

        with self.assertRaisesMessage(ValidationError, "não pode ser alterado"):
            snapshot.save()

        snapshot.refresh_from_db()
        snapshot.source_component = None
        with self.assertRaisesMessage(ValidationError, "não pode ser alterado"):
            snapshot.save()

    def test_cancellation_after_recipe_edit_restores_original_fifo_allocations(self):
        drink = self.prepared()
        spirit = self.ingredient("Cachaça", "volume")
        component = self.component(drink, spirit, "50", "mL")
        older_time, newer_time = fifo_times()
        older = make_entry(
            product=spirit,
            quantity="60",
            created_at=older_time,
        )
        newer = make_entry(
            product=spirit,
            quantity="100",
            created_at=newer_time,
        )
        order, _items = self.make_order([(drink, "2", "20")])
        self.approve(order)
        component.quantity = D("80")
        component.unit = "mL"
        component.save()

        cancel_paid_order_with_stock_return(
            order_id=order.pk,
            company=self.company,
            user=self.user,
        )

        older.refresh_from_db()
        newer.refresh_from_db()
        returns = StockMovement.objects.filter(movement_type="return_to_stock")
        self.assertEqual(older.remaining_quantity, D("60"))
        self.assertEqual(newer.remaining_quantity, D("100"))
        self.assertEqual(sum((movement.quantity for movement in returns), D("0")), D("100"))
        for movement in returns:
            self.assertIsNotNone(movement.sale_item_component_id)
            self.assertEqual(
                movement.sale_item_component_id,
                movement.reversal_of.sale_item_component_id,
            )

    def test_discard_preserves_component_consumption(self):
        drink = self.prepared()
        spirit = self.ingredient("Cachaça", "volume")
        self.component(drink, spirit, "50", "mL")
        entry = make_entry(product=spirit, quantity="500")
        order, _items = self.make_order([(drink, "2", "20")])
        self.approve(order)

        result = discard_paid_order(
            order_id=order.pk,
            company=self.company,
            user=self.user,
        )

        entry.refresh_from_db()
        self.assertTrue(result.changed)
        self.assertEqual(entry.remaining_quantity, D("400"))
        self.assertFalse(
            StockMovement.objects.filter(movement_type="return_to_stock").exists()
        )

    def test_cross_company_ingredient_is_rejected_even_if_database_is_corrupt(self):
        drink = self.prepared()
        other_company = make_company(name="Outra empresa")
        other_unit = make_unit(company=other_company)
        foreign = make_product(
            company=other_company,
            unit=other_unit,
            inventory_role="input",
            stock_dimension="volume",
        )
        ProductComponent.objects.bulk_create(
            [
                ProductComponent(
                    company=self.company,
                    product=drink,
                    ingredient=foreign,
                    quantity=D("50"),
                    unit="mL",
                )
            ]
        )
        order, _items = self.make_order([(drink, "1", "20")])

        with self.assertRaises(InvalidOperationalRecipe):
            self.approve(order)

        self.assert_approval_rolled_back(order, [])

    def test_empty_recipe_is_rejected_without_requiring_own_stock(self):
        drink = self.prepared()
        order, _items = self.make_order([(drink, "1", "20")])

        with self.assertRaisesMessage(
            InvalidOperationalRecipe,
            "não possui componentes",
        ):
            self.approve(order)

        self.assert_approval_rolled_back(order, [])

    def test_invalid_recipe_is_reported_by_approval_view_without_server_error(self):
        drink = self.prepared()
        order, _items = self.make_order([(drink, "1", "20")])
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("orders:approve_order", args=[order.pk, "pix"]),
        )
        messages = "\n".join(
            str(message) for message in get_messages(response.wsgi_request)
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("não possui componentes", messages)
        self.assert_approval_rolled_back(order, [])

    def test_prepared_dose_uses_component_quantity_not_own_stock(self):
        drink = self.prepared(
            sale_form="dose",
            stock_dimension="volume",
            dose_ml="60",
        )
        spirit = self.ingredient("Cachaça", "volume")
        self.component(drink, spirit, "50", "mL")
        entry = make_entry(product=spirit, quantity="500")
        order, _items = self.make_order([(drink, "2", "20")])

        result = self.approve(order)

        entry.refresh_from_db()
        sale_item = result.sale.items.get()
        self.assertEqual(entry.remaining_quantity, D("400"))
        self.assertEqual(sale_item.physical_quantity_total, D("120"))
        self.assertEqual(
            sale_item.component_snapshots.get().physical_quantity_total,
            D("100"),
        )

    def test_pre_portioned_product_does_not_consume_components_automatically(self):
        product = self.prepared(
            name="Porção pronta",
            inventory_role="prepared",
            preparation_mode="pre_portioned",
        )
        ingredient = self.ingredient("Matéria-prima", "weight")
        self.component(product, ingredient, "400", "g")
        product_entry = make_entry(product=product, quantity="3")
        ingredient_entry = make_entry(product=ingredient, quantity="5000")
        order, _items = self.make_order([(product, "1", "20")])

        result = self.approve(order)

        product_entry.refresh_from_db()
        ingredient_entry.refresh_from_db()
        self.assertEqual(product_entry.remaining_quantity, D("2"))
        self.assertEqual(ingredient_entry.remaining_quantity, D("5000"))
        self.assertFalse(result.sale.items.get().component_snapshots.exists())
        self.assertEqual(
            StockMovement.objects.get(movement_type="sale").product,
            product,
        )
