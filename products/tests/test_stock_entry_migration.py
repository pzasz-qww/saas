from decimal import Decimal

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class StockEntryLotDataMigrationTests(TransactionTestCase):
    migrate_from = ("products", "0007_productcomponent_product_dose_ml_and_more")
    migrate_to = ("products", "0009_stock_entry_remove_legacy_modes")

    def setUp(self):
        super().setUp()
        self.addCleanup(self._restore_latest_migrations)

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        old_apps = executor.loader.project_state([self.migrate_from]).apps

        Company = old_apps.get_model("companies", "Company")
        Product = old_apps.get_model("products", "Product")
        StockEntry = old_apps.get_model("products", "StockEntry")
        Unit = old_apps.get_model("products", "Unit")

        company = Company.objects.create(name="Empresa lotes legados")
        unit = Unit.objects.create(company=company, name="Unidade", symbol="un")
        self.entry_ids = {}
        for dimension, quantity in (
            ("count", "20"),
            ("weight", "30000"),
            ("volume", "5000"),
        ):
            product = Product.objects.create(
                company=company,
                unit=unit,
                name=f"Produto {dimension}",
                stock_dimension=dimension,
            )
            entry = StockEntry.objects.create(
                company=company,
                product=product,
                total_cost=Decimal("10"),
                quantity_added=Decimal(quantity),
                remaining_quantity=Decimal(quantity),
            )
            self.entry_ids[dimension] = entry.pk

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])
        self.apps = executor.loader.project_state([self.migrate_to]).apps

    def _restore_latest_migrations(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_legacy_quantity_becomes_original_quantity_in_the_base_unit(self):
        StockEntry = self.apps.get_model("products", "StockEntry")
        expected_units = {"count": "unit", "weight": "g", "volume": "mL"}
        for dimension, entry_id in self.entry_ids.items():
            with self.subTest(dimension=dimension):
                entry = StockEntry.objects.get(pk=entry_id)
                self.assertEqual(entry.input_quantity, entry.quantity_added)
                self.assertEqual(entry.input_unit, expected_units[dimension])
                self.assertEqual(entry.base_unit, expected_units[dimension])
