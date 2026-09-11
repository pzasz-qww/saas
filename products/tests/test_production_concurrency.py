from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier, Event
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connections
from django.test import TransactionTestCase, skipUnlessDBFeature

from companies.models import Company
from orders.models import Order, OrderItem
from orders.services import approve_order
from products.models import Product, ProductComponent, Production, StockEntry
from products.production_services import (
    ProductionReversalError,
    create_production,
    reverse_production,
)
from products.services import InsufficientStock

from .helpers import make_company, make_entry, make_product, make_user


D = Decimal


@skipUnlessDBFeature("has_select_for_update")
class ProductionConcurrencyTests(TransactionTestCase):
    """PostgreSQL gate tests; SQLite intentionally skips real row-lock tests."""

    reset_sequences = True

    def setUp(self):
        self.company = make_company(name="Bar concorrente")
        self.user = make_user(company=self.company, role="owner")

    def prepared(self, name="Porção pronta", mode="pre_portioned"):
        return make_product(
            company=self.company,
            name=name,
            inventory_role="prepared",
            preparation_mode=mode,
        )

    def ingredient(self):
        return make_product(
            company=self.company,
            name="Ingrediente compartilhado",
            inventory_role="input",
            product_type="internal_use",
            stock_dimension="weight",
        )

    def component(self, product, ingredient, quantity="500"):
        return ProductComponent.objects.create(
            company=self.company,
            product=product,
            ingredient=ingredient,
            quantity=D(quantity),
            unit="g",
        )

    def production_call(self, product_id):
        return create_production(
            company=Company.objects.get(pk=self.company.pk),
            product=Product.objects.get(pk=product_id),
            planned_quantity=D("1"),
            produced_quantity=D("1"),
            created_by=get_user_model().objects.get(pk=self.user.pk),
        )

    def run_workers(self, *workers):
        barrier = Barrier(len(workers))

        def run(worker):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return worker()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(workers)) as executor:
            futures = [executor.submit(run, worker) for worker in workers]
            return [future.result(timeout=30) for future in futures]

    def test_two_productions_competing_for_last_ingredient(self):
        product = self.prepared()
        ingredient = self.ingredient()
        self.component(product, ingredient)
        entry = make_entry(product=ingredient, quantity="500")

        def produce():
            try:
                self.production_call(product.pk)
            except InsufficientStock:
                return "insufficient"
            return "produced"

        results = self.run_workers(produce, produce)

        entry.refresh_from_db()
        self.assertCountEqual(results, ["produced", "insufficient"])
        self.assertEqual(entry.remaining_quantity, D("0"))
        self.assertEqual(Production.objects.count(), 1)

    def test_production_competes_with_on_demand_sale_for_same_ingredient(self):
        pre_portioned = self.prepared()
        on_demand = self.prepared("Drink", mode="on_demand")
        ingredient = self.ingredient()
        self.component(pre_portioned, ingredient)
        self.component(on_demand, ingredient)
        entry = make_entry(product=ingredient, quantity="500")
        order = Order.objects.create(company=self.company, status="pre_sale")
        OrderItem.objects.create(
            order=order,
            company=self.company,
            product=on_demand,
            quantity=D("1"),
        )

        def produce():
            try:
                self.production_call(pre_portioned.pk)
            except InsufficientStock:
                return "production_insufficient"
            return "produced"

        def sell():
            try:
                approve_order(
                    order_id=order.pk,
                    company=Company.objects.get(pk=self.company.pk),
                    payment_method="pix",
                    user=get_user_model().objects.get(pk=self.user.pk),
                )
            except InsufficientStock:
                return "sale_insufficient"
            return "sold"

        results = self.run_workers(produce, sell)

        entry.refresh_from_db()
        self.assertIn(
            sorted(results),
            [sorted(["produced", "sale_insufficient"]), sorted(["sold", "production_insufficient"])],
        )
        self.assertEqual(entry.remaining_quantity, D("0"))

    def test_two_simultaneous_reversals_are_idempotent(self):
        product = self.prepared()
        ingredient = self.ingredient()
        self.component(product, ingredient)
        entry = make_entry(product=ingredient, quantity="500")
        production = self.production_call(product.pk).production

        def reverse():
            return reverse_production(
                company=Company.objects.get(pk=self.company.pk),
                production_id=production.pk,
                user=get_user_model().objects.get(pk=self.user.pk),
            ).reversed

        results = self.run_workers(reverse, reverse)

        entry.refresh_from_db()
        self.assertCountEqual(results, [True, False])
        self.assertEqual(entry.remaining_quantity, D("500"))

    def test_sale_of_last_output_competes_with_production_reversal(self):
        product = self.prepared()
        ingredient = self.ingredient()
        self.component(product, ingredient)
        ingredient_entry = make_entry(product=ingredient, quantity="500")
        production = self.production_call(product.pk).production
        output = StockEntry.objects.get(production=production)
        order = Order.objects.create(company=self.company, status="pre_sale")
        OrderItem.objects.create(
            order=order,
            company=self.company,
            product=product,
            quantity=D("1"),
        )

        def sell():
            try:
                approve_order(
                    order_id=order.pk,
                    company=Company.objects.get(pk=self.company.pk),
                    payment_method="pix",
                    user=get_user_model().objects.get(pk=self.user.pk),
                )
            except InsufficientStock:
                return "sale_insufficient"
            return "sold"

        def reverse():
            try:
                reverse_production(
                    company=Company.objects.get(pk=self.company.pk),
                    production_id=production.pk,
                    user=get_user_model().objects.get(pk=self.user.pk),
                )
            except ProductionReversalError:
                return "reversal_blocked"
            return "reversed"

        results = self.run_workers(sell, reverse)

        output.refresh_from_db()
        ingredient_entry.refresh_from_db()
        self.assertIn(
            sorted(results),
            [sorted(["sold", "reversal_blocked"]), sorted(["sale_insufficient", "reversed"])],
        )
        self.assertEqual(output.remaining_quantity, D("0"))
        self.assertIn(ingredient_entry.remaining_quantity, {D("0"), D("500")})

    def test_component_change_waits_for_production_snapshot(self):
        product = self.prepared()
        ingredient = self.ingredient()
        component = self.component(product, ingredient)
        make_entry(product=ingredient, quantity="1000")
        production_has_lock = Event()
        release_production = Event()
        edit_started = Event()
        from products import production_services

        real_consume = production_services.consume_production_stock

        def blocking_consume(*args, **kwargs):
            production_has_lock.set()
            if not release_production.wait(timeout=10):
                raise AssertionError("Tempo esgotado aguardando liberação da produção")
            return real_consume(*args, **kwargs)

        def produce():
            close_old_connections()
            try:
                return self.production_call(product.pk).production.pk
            finally:
                connections.close_all()

        def edit():
            close_old_connections()
            try:
                editable = ProductComponent.objects.get(pk=component.pk)
                editable.quantity = D("600")
                editable.unit = "g"
                edit_started.set()
                editable.save()
                return editable.quantity
            finally:
                connections.close_all()

        with patch(
            "products.production_services.consume_production_stock",
            side_effect=blocking_consume,
        ):
            with ThreadPoolExecutor(max_workers=2) as executor:
                production_future = executor.submit(produce)
                self.assertTrue(production_has_lock.wait(timeout=10))
                edit_future = executor.submit(edit)
                self.assertTrue(edit_started.wait(timeout=10))
                release_production.set()
                production_id = production_future.result(timeout=30)
                edited_quantity = edit_future.result(timeout=30)

        snapshot = Production.objects.get(pk=production_id).consumptions.get()
        self.assertEqual(snapshot.theoretical_quantity, D("500"))
        self.assertEqual(edited_quantity, D("600"))
