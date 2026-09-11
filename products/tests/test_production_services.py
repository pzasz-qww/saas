from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from orders.models import Order, OrderItem
from orders.services import approve_order, cancel_paid_order_with_stock_return
from products.models import (
    ProductComponent,
    Production,
    ProductionConsumption,
    StockEntry,
    StockMovement,
)
from products.production_services import (
    InvalidProduction,
    ProductionReversalError,
    create_production,
    reverse_production,
)
from products.recipe_services import get_product_availability, get_production_potential
from products.services import InsufficientStock, InvalidStockOperation

from .helpers import make_company, make_entry, make_product, make_user


D = Decimal


class ProductionServiceTests(TestCase):
    def setUp(self):
        self.company = make_company(name="Bar Produção")
        self.user = make_user(company=self.company, role="owner")

    def prepared(self, name="Porção de carne", **overrides):
        values = {
            "company": self.company,
            "name": name,
            "inventory_role": "prepared",
            "preparation_mode": "pre_portioned",
            "product_type": "sale",
            "sale_price": "30",
        }
        values.update(overrides)
        return make_product(**values)

    def ingredient(self, name, dimension="count"):
        return make_product(
            company=self.company,
            name=name,
            inventory_role="input",
            product_type="internal_use",
            stock_dimension=dimension,
        )

    def component(self, product, ingredient, quantity, unit):
        return ProductComponent.objects.create(
            company=self.company,
            product=product,
            ingredient=ingredient,
            quantity=D(quantity),
            unit=unit,
        )

    def produce(self, product, **overrides):
        values = {
            "company": self.company,
            "product": product,
            "planned_quantity": D("10"),
            "produced_quantity": D("8"),
            "production_date": date(2026, 9, 5),
            "expiration_date": date(2026, 9, 7),
            "created_by": self.user,
        }
        values.update(overrides)
        return create_production(**values)

    def test_production_potential_uses_limiting_ingredient_without_releasing_sale(self):
        product = self.prepared()
        meat = self.ingredient("Carne", "weight")
        package = self.ingredient("Embalagem")
        self.component(product, meat, "500", "g")
        self.component(product, package, "1", "unit")
        make_entry(product=meat, quantity="5000")
        make_entry(product=package, quantity="30")

        potential = get_production_potential(product)
        available_now = get_product_availability(product)

        self.assertEqual(potential.available_quantity, D("10"))
        self.assertEqual(potential.limiting_component.ingredient, meat)
        self.assertEqual(available_now.available_quantity, D("0"))

        order = Order.objects.create(
            company=self.company,
            status="pre_sale",
            created_by=self.user,
        )
        OrderItem.objects.create(
            order=order,
            company=self.company,
            product=product,
            quantity=D("1"),
        )
        with self.assertRaises(InsufficientStock):
            approve_order(
                order_id=order.pk,
                company=self.company,
                payment_method="pix",
                user=self.user,
            )
        self.assertEqual(meat.current_stock, D("5000"))

    def test_production_consumes_components_and_creates_costed_output_lot(self):
        product = self.prepared()
        meat = self.ingredient("Carne", "weight")
        package = self.ingredient("Embalagem")
        meat_component = self.component(product, meat, "500", "g")
        package_component = self.component(product, package, "1", "unit")
        meat_entry = make_entry(product=meat, quantity="5000", total_cost="120")
        package_entry = make_entry(
            product=package,
            quantity="10",
            total_cost="10",
        )

        result = self.produce(product)

        meat_entry.refresh_from_db()
        package_entry.refresh_from_db()
        production = result.production
        output = result.output_entry
        self.assertEqual(meat_entry.remaining_quantity, D("0"))
        self.assertEqual(package_entry.remaining_quantity, D("0"))
        self.assertEqual(output.product, product)
        self.assertEqual(output.production, production)
        self.assertEqual(output.quantity_added, D("8"))
        self.assertEqual(output.remaining_quantity, D("8"))
        self.assertEqual(output.total_cost, D("130"))
        self.assertEqual(output.expiration_date, date(2026, 9, 7))
        self.assertEqual(production.total_cost, D("130"))
        self.assertEqual(production.unit_cost, D("16.25"))
        self.assertEqual(production.theoretical_yield, D("10"))
        self.assertEqual(production.actual_yield, D("8"))
        self.assertEqual(production.yield_percentage, D("80"))
        self.assertEqual(production.yield_difference, D("2"))
        consumptions = {
            item.source_component_id: item
            for item in production.consumptions.all()
        }
        self.assertEqual(consumptions[meat_component.pk].theoretical_quantity, D("5000"))
        self.assertEqual(consumptions[package_component.pk].actual_quantity, D("10"))
        self.assertEqual(
            StockMovement.objects.filter(
                production=production,
                movement_type="production_consumption",
            ).count(),
            2,
        )
        self.assertEqual(
            StockMovement.objects.get(
                production=production,
                movement_type="production_output",
            ).stock_entry,
            output,
        )

    def test_production_component_crosses_fifo_lots(self):
        product = self.prepared()
        meat = self.ingredient("Carne", "weight")
        self.component(product, meat, "500", "g")
        older = make_entry(product=meat, quantity="2000", total_cost="40")
        newer = make_entry(product=meat, quantity="4000", total_cost="120")
        StockEntry.objects.filter(pk=older.pk).update(created_at="2026-09-01T10:00:00Z")
        StockEntry.objects.filter(pk=newer.pk).update(created_at="2026-09-02T10:00:00Z")

        result = self.produce(product)

        older.refresh_from_db()
        newer.refresh_from_db()
        movements = list(
            StockMovement.objects.filter(
                production=result.production,
                movement_type="production_consumption",
            ).order_by("stock_entry__created_at", "stock_entry_id")
        )
        self.assertEqual(older.remaining_quantity, D("0"))
        self.assertEqual(newer.remaining_quantity, D("1000"))
        self.assertEqual([item.quantity for item in movements], [D("2000"), D("3000")])
        self.assertEqual(sum((item.cost_value for item in movements), D("0")), D("130"))
        self.assertEqual(result.output_entry.total_cost, D("130"))

    def test_insufficient_component_creates_nothing_and_changes_no_stock(self):
        product = self.prepared()
        meat = self.ingredient("Carne", "weight")
        package = self.ingredient("Embalagem")
        self.component(product, meat, "500", "g")
        self.component(product, package, "1", "unit")
        meat_entry = make_entry(product=meat, quantity="4999")
        package_entry = make_entry(product=package, quantity="10")

        with self.assertRaises(InsufficientStock):
            self.produce(product)

        meat_entry.refresh_from_db()
        package_entry.refresh_from_db()
        self.assertEqual(meat_entry.remaining_quantity, D("4999"))
        self.assertEqual(package_entry.remaining_quantity, D("10"))
        self.assertFalse(Production.objects.exists())
        self.assertFalse(ProductionConsumption.objects.exists())
        self.assertFalse(StockMovement.objects.exists())

    def test_failure_before_output_lot_rolls_back_every_consumption(self):
        product = self.prepared()
        meat = self.ingredient("Carne", "weight")
        self.component(product, meat, "500", "g")
        meat_entry = make_entry(product=meat, quantity="5000")

        with patch(
            "products.production_services.StockEntry.objects.create",
            side_effect=RuntimeError("falha ao criar lote"),
        ):
            with self.assertRaisesRegex(RuntimeError, "criar lote"):
                self.produce(product)

        meat_entry.refresh_from_db()
        self.assertEqual(meat_entry.remaining_quantity, D("5000"))
        self.assertFalse(Production.objects.exists())
        self.assertFalse(ProductionConsumption.objects.exists())
        self.assertFalse(StockMovement.objects.exists())

    def test_real_consumption_and_loss_do_not_create_double_deduction(self):
        product = self.prepared()
        meat = self.ingredient("Carne", "weight")
        component = self.component(product, meat, "500", "g")
        meat_entry = make_entry(product=meat, quantity="6000", total_cost="120")

        result = self.produce(
            product,
            component_values={
                component.pk: {
                    "actual_quantity": D("4850"),
                    "loss_quantity": D("1000"),
                }
            },
        )

        meat_entry.refresh_from_db()
        consumption = result.production.consumptions.get()
        movement = consumption.stock_movements.get(
            movement_type="production_consumption"
        )
        self.assertEqual(consumption.theoretical_quantity, D("5000"))
        self.assertEqual(consumption.actual_quantity, D("4850"))
        self.assertEqual(consumption.loss_quantity, D("1000"))
        self.assertEqual(movement.quantity, D("4850"))
        self.assertEqual(meat_entry.remaining_quantity, D("1150"))
        self.assertEqual(StockMovement.objects.filter(production=result.production).count(), 2)

    def test_repeating_fifo_unit_cost_is_persisted_with_stock_precision(self):
        product = self.prepared()
        package = self.ingredient("Embalagem")
        self.component(product, package, "1", "unit")
        make_entry(product=package, quantity="3", total_cost="1")

        result = self.produce(
            product,
            planned_quantity=D("1"),
            produced_quantity=D("1"),
        )

        result.production.refresh_from_db()
        result.output_entry.refresh_from_db()
        movement = result.production.stock_movements.get(
            movement_type="production_consumption"
        )
        self.assertEqual(result.production.total_cost, D("0.3333333333"))
        self.assertEqual(result.output_entry.total_cost, D("0.3333333333"))
        self.assertEqual(movement.cost_value, D("0.3333333333"))

    def test_sale_and_cancellation_use_only_the_produced_lot(self):
        product = self.prepared()
        meat = self.ingredient("Carne", "weight")
        self.component(product, meat, "500", "g")
        meat_entry = make_entry(product=meat, quantity="5000", total_cost="100")
        production_result = self.produce(product)
        order = Order.objects.create(
            company=self.company,
            status="pre_sale",
            created_by=self.user,
        )
        OrderItem.objects.create(
            order=order,
            company=self.company,
            product=product,
            quantity=D("3"),
        )

        approval = approve_order(
            order_id=order.pk,
            company=self.company,
            payment_method="pix",
            user=self.user,
        )

        meat_entry.refresh_from_db()
        production_result.output_entry.refresh_from_db()
        self.assertEqual(meat_entry.remaining_quantity, D("0"))
        self.assertEqual(production_result.output_entry.remaining_quantity, D("5"))
        sale_movement = StockMovement.objects.get(
            movement_type="sale",
            sale_item__sale=approval.sale,
        )
        self.assertEqual(sale_movement.product, product)
        self.assertEqual(sale_movement.stock_entry, production_result.output_entry)
        self.assertEqual(approval.sale.total_cost, D("37.5"))

        cancel_paid_order_with_stock_return(
            order_id=order.pk,
            company=self.company,
            user=self.user,
        )
        meat_entry.refresh_from_db()
        production_result.output_entry.refresh_from_db()
        self.assertEqual(meat_entry.remaining_quantity, D("0"))
        self.assertEqual(production_result.output_entry.remaining_quantity, D("8"))

    def test_portion_output_uses_physical_engine_but_reports_commercial_units(self):
        product = self.prepared(
            sale_form="portion",
            stock_dimension="weight",
            portion_g="400",
        )
        meat = self.ingredient("Carne", "weight")
        self.component(product, meat, "500", "g")
        make_entry(product=meat, quantity="5000")

        result = self.produce(product)

        self.assertEqual(result.production.produced_quantity, D("8"))
        self.assertEqual(result.output_entry.quantity_added, D("3200"))
        self.assertEqual(result.output_entry.base_unit, "g")
        self.assertEqual(
            get_product_availability(product).available_quantity,
            D("8"),
        )

    def test_intact_production_reversal_restores_original_lots(self):
        product = self.prepared()
        meat = self.ingredient("Carne", "weight")
        self.component(product, meat, "500", "g")
        older = make_entry(product=meat, quantity="2000")
        newer = make_entry(product=meat, quantity="4000")
        StockEntry.objects.filter(pk=older.pk).update(created_at="2026-09-01T10:00:00Z")
        StockEntry.objects.filter(pk=newer.pk).update(created_at="2026-09-02T10:00:00Z")
        production_result = self.produce(product)

        reversal = reverse_production(
            company=self.company,
            production_id=production_result.production.pk,
            user=self.user,
        )

        older.refresh_from_db()
        newer.refresh_from_db()
        production_result.output_entry.refresh_from_db()
        production_result.production.refresh_from_db()
        self.assertTrue(reversal.reversed)
        self.assertEqual(older.remaining_quantity, D("2000"))
        self.assertEqual(newer.remaining_quantity, D("4000"))
        self.assertEqual(production_result.output_entry.remaining_quantity, D("0"))
        self.assertEqual(production_result.production.status, "reversed")
        self.assertEqual(
            StockMovement.objects.filter(
                production=production_result.production,
                movement_type="production_return",
            ).count(),
            2,
        )
        self.assertEqual(
            StockMovement.objects.filter(
                production=production_result.production,
                movement_type="production_output_reversal",
            ).count(),
            1,
        )

    def test_repeated_reversal_is_idempotent(self):
        product = self.prepared()
        meat = self.ingredient("Carne", "weight")
        self.component(product, meat, "500", "g")
        ingredient_entry = make_entry(product=meat, quantity="5000")
        result = self.produce(product)

        first = reverse_production(
            company=self.company,
            production_id=result.production.pk,
            user=self.user,
        )
        second = reverse_production(
            company=self.company,
            production_id=result.production.pk,
            user=self.user,
        )

        ingredient_entry.refresh_from_db()
        self.assertTrue(first.reversed)
        self.assertFalse(second.reversed)
        self.assertEqual(ingredient_entry.remaining_quantity, D("5000"))
        self.assertEqual(
            StockMovement.objects.filter(
                production=result.production,
                movement_type="production_return",
            ).count(),
            1,
        )

    def test_reversal_uses_snapshot_after_recipe_is_changed(self):
        product = self.prepared()
        meat = self.ingredient("Carne", "weight")
        component = self.component(product, meat, "500", "g")
        entry = make_entry(product=meat, quantity="5000")
        result = self.produce(product)
        component.quantity = D("600")
        component.unit = "g"
        component.save()

        reverse_production(
            company=self.company,
            production_id=result.production.pk,
            user=self.user,
        )

        entry.refresh_from_db()
        snapshot = result.production.consumptions.get()
        self.assertEqual(snapshot.theoretical_quantity, D("5000"))
        self.assertEqual(entry.remaining_quantity, D("5000"))

    def test_reversal_uses_output_lot_snapshot_after_portion_size_changes(self):
        product = self.prepared(
            sale_form="portion",
            stock_dimension="weight",
            portion_g="400",
        )
        meat = self.ingredient("Carne", "weight")
        self.component(product, meat, "500", "g")
        ingredient_entry = make_entry(product=meat, quantity="5000")
        result = self.produce(product)
        self.assertEqual(result.output_entry.quantity_added, D("3200"))

        product.portion_g = D("500")
        product.save(update_fields=["portion_g"])
        reversal = reverse_production(
            company=self.company,
            production_id=result.production.pk,
            user=self.user,
        )

        ingredient_entry.refresh_from_db()
        result.output_entry.refresh_from_db()
        self.assertTrue(reversal.reversed)
        self.assertEqual(result.output_entry.remaining_quantity, D("0"))
        self.assertEqual(ingredient_entry.remaining_quantity, D("5000"))

    def test_partially_sold_output_blocks_simple_reversal(self):
        product = self.prepared()
        meat = self.ingredient("Carne", "weight")
        self.component(product, meat, "500", "g")
        meat_entry = make_entry(product=meat, quantity="5000")
        production_result = self.produce(product)
        order = Order.objects.create(company=self.company, status="pre_sale")
        OrderItem.objects.create(
            order=order,
            company=self.company,
            product=product,
            quantity=D("3"),
        )
        approve_order(
            order_id=order.pk,
            company=self.company,
            payment_method="pix",
            user=self.user,
        )

        with self.assertRaisesMessage(ProductionReversalError, "não está intacto"):
            reverse_production(
                company=self.company,
                production_id=production_result.production.pk,
                user=self.user,
            )

        meat_entry.refresh_from_db()
        production_result.output_entry.refresh_from_db()
        production_result.production.refresh_from_db()
        self.assertEqual(meat_entry.remaining_quantity, D("0"))
        self.assertEqual(production_result.output_entry.remaining_quantity, D("5"))
        self.assertEqual(production_result.production.status, "completed")

    def test_cross_company_product_and_empty_recipe_are_rejected(self):
        foreign_company = make_company(name="Outro bar")
        foreign_product = make_product(
            company=foreign_company,
            inventory_role="prepared",
            preparation_mode="pre_portioned",
        )
        with self.assertRaises(InvalidStockOperation):
            self.produce(foreign_product)

        product = self.prepared()
        with self.assertRaisesMessage(InvalidProduction, "não possui componentes"):
            self.produce(product)

    def test_corrupt_cross_company_component_is_rejected_without_stock_change(self):
        product = self.prepared()
        foreign_company = make_company(name="Fornecedor de outro bar")
        foreign_ingredient = make_product(
            company=foreign_company,
            inventory_role="input",
            product_type="internal_use",
            stock_dimension="weight",
        )
        foreign_entry = make_entry(product=foreign_ingredient, quantity="5000")
        ProductComponent.objects.bulk_create(
            [
                ProductComponent(
                    company=self.company,
                    product=product,
                    ingredient=foreign_ingredient,
                    quantity=D("500"),
                    unit="g",
                )
            ]
        )

        with self.assertRaises(InvalidProduction):
            self.produce(product)

        foreign_entry.refresh_from_db()
        self.assertEqual(foreign_entry.remaining_quantity, D("5000"))
        self.assertFalse(Production.objects.exists())
