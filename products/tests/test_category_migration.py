from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class ProductCategoryDataMigrationTests(TransactionTestCase):
    migrate_from = ("products", "0003_stockmovement_origin_and_protection")
    migrate_to = ("products", "0006_migrate_product_categories")

    def setUp(self):
        super().setUp()
        self.addCleanup(self._restore_latest_migrations)

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        old_apps = executor.loader.project_state([self.migrate_from]).apps

        Company = old_apps.get_model("companies", "Company")
        Product = old_apps.get_model("products", "Product")
        Unit = old_apps.get_model("products", "Unit")

        self.company_a = Company.objects.create(name="Empresa A")
        self.company_b = Company.objects.create(name="Empresa B")
        unit_a = Unit.objects.create(
            company=self.company_a,
            name="Unidade A",
            symbol="un-a",
        )
        unit_b = Unit.objects.create(
            company=self.company_b,
            name="Unidade B",
            symbol="un-b",
        )

        self.product_ids = {}

        def create_product(key, *, company, unit, category):
            product = Product.objects.create(
                company=company,
                unit=unit,
                name=f"Produto {key}",
                category=category,
                product_type="sale",
            )
            self.product_ids[key] = product.pk

        create_product(
            "beer_first",
            company=self.company_a,
            unit=unit_a,
            category="  Cervejas  ",
        )
        create_product(
            "beer_lower",
            company=self.company_a,
            unit=unit_a,
            category="cervejas",
        )
        create_product(
            "beer_upper",
            company=self.company_a,
            unit=unit_a,
            category="CERVEJAS",
        )
        create_product(
            "portions_accented",
            company=self.company_a,
            unit=unit_a,
            category="Porções",
        )
        create_product(
            "portions_ascii",
            company=self.company_a,
            unit=unit_a,
            category="Porcoes",
        )
        create_product(
            "empty",
            company=self.company_a,
            unit=unit_a,
            category="",
        )
        create_product(
            "whitespace",
            company=self.company_a,
            unit=unit_a,
            category="   ",
        )
        create_product(
            "null",
            company=self.company_a,
            unit=unit_a,
            category=None,
        )
        create_product(
            "explicit_uncategorized",
            company=self.company_a,
            unit=unit_a,
            category="Sem categoria",
        )
        create_product(
            "beer_other_company",
            company=self.company_b,
            unit=unit_b,
            category="cervejas",
        )

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])
        self.apps = executor.loader.project_state([self.migrate_to]).apps

    def _restore_latest_migrations(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def product(self, key):
        Product = self.apps.get_model("products", "Product")
        return Product.objects.get(pk=self.product_ids[key])

    def test_legacy_categories_are_migrated_without_crossing_company_boundaries(self):
        Category = self.apps.get_model("products", "Category")

        beer_first = self.product("beer_first")
        beer_lower = self.product("beer_lower")
        beer_upper = self.product("beer_upper")
        portions_accented = self.product("portions_accented")
        portions_ascii = self.product("portions_ascii")
        other_company_beer = self.product("beer_other_company")

        self.assertEqual(beer_first.category_id, beer_lower.category_id)
        self.assertEqual(beer_first.category_id, beer_upper.category_id)
        self.assertEqual(
            portions_accented.category_id,
            portions_ascii.category_id,
        )
        self.assertNotEqual(
            beer_first.category_id,
            other_company_beer.category_id,
        )

        beer_category = Category.objects.get(pk=beer_first.category_id)
        portions_category = Category.objects.get(pk=portions_accented.category_id)
        other_company_category = Category.objects.get(
            pk=other_company_beer.category_id
        )

        self.assertEqual(beer_category.company_id, self.company_a.pk)
        self.assertEqual(other_company_category.company_id, self.company_b.pk)
        self.assertEqual(beer_category.name, "Cervejas")
        self.assertEqual(beer_category.normalized_name, "cervejas")
        self.assertEqual(portions_category.name, "Porções")
        self.assertEqual(portions_category.normalized_name, "porcoes")

        for key in ("empty", "whitespace", "null"):
            with self.subTest(key=key):
                self.assertIsNone(self.product(key).category_id)

        explicit_uncategorized = self.product("explicit_uncategorized")
        self.assertIsNotNone(explicit_uncategorized.category_id)
        self.assertEqual(explicit_uncategorized.category.name, "Sem categoria")
        self.assertFalse(Category.objects.filter(normalized_name="").exists())

        self.assertEqual(
            self.product("beer_first").category_legacy,
            "  Cervejas  ",
        )
        self.assertEqual(self.product("whitespace").category_legacy, "   ")
        self.assertIsNone(self.product("null").category_legacy)

        self.assertEqual(
            Category.objects.filter(company_id=self.company_a.pk).count(),
            3,
        )
        self.assertEqual(
            Category.objects.filter(company_id=self.company_b.pk).count(),
            1,
        )
