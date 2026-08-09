from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from products.category_services import resolve_category
from products.models import Category, Product

from .helpers import make_company, make_product, make_unit


class CategoryModelAndResolutionTests(TestCase):
    def setUp(self):
        self.company = make_company(name="Empresa principal")

    def test_save_cleans_visible_name_and_populates_normalized_name(self):
        category = Category.objects.create(
            company=self.company,
            name="  Bebidas   sem álcool  ",
        )

        self.assertEqual(category.name, "Bebidas sem álcool")
        self.assertEqual(category.normalized_name, "bebidas sem alcool")
        self.assertTrue(category.active)
        self.assertEqual(str(category), "Bebidas sem álcool")

    def test_equivalent_names_resolve_to_the_same_category(self):
        variants = (
            "Cervejas",
            "cervejas",
            " Cervejas ",
            "CERVEJAS",
        )

        categories = [
            resolve_category(company=self.company, raw_name=name)
            for name in variants
        ]

        self.assertEqual({category.pk for category in categories}, {categories[0].pk})
        self.assertEqual(categories[0].name, "Cervejas")
        self.assertEqual(Category.objects.count(), 1)

    def test_accented_and_ascii_names_resolve_to_the_same_category(self):
        accented = resolve_category(
            company=self.company,
            raw_name="Porções",
        )
        ascii_name = resolve_category(
            company=self.company,
            raw_name="Porcoes",
        )

        self.assertEqual(accented.pk, ascii_name.pk)
        self.assertEqual(accented.name, "Porções")
        self.assertEqual(accented.normalized_name, "porcoes")

    def test_same_normalized_name_is_allowed_in_different_companies(self):
        other_company = make_company(name="Outra empresa")

        own = resolve_category(company=self.company, raw_name="Cervejas")
        other = resolve_category(company=other_company, raw_name="cervejas")

        self.assertNotEqual(own.pk, other.pk)
        self.assertEqual(own.company, self.company)
        self.assertEqual(other.company, other_company)
        self.assertEqual(Category.objects.count(), 2)

    def test_database_constraint_rejects_duplicate_normalized_name(self):
        Category.objects.create(company=self.company, name="Cervejas")

        with self.assertRaises(IntegrityError), transaction.atomic():
            Category.objects.create(company=self.company, name=" cervejas ")

        self.assertEqual(Category.objects.count(), 1)

    def test_empty_category_is_not_created(self):
        for value in (None, "", "   "):
            with self.subTest(value=value):
                self.assertIsNone(
                    resolve_category(company=self.company, raw_name=value)
                )

        self.assertFalse(Category.objects.exists())

    def test_empty_category_model_name_is_rejected(self):
        with self.assertRaises(ValidationError):
            Category.objects.create(company=self.company, name="   ")

        self.assertFalse(Category.objects.exists())

    def test_visible_name_longer_than_legacy_limit_is_rejected(self):
        with self.assertRaisesMessage(ValidationError, "80 caracteres"):
            Category.objects.create(
                company=self.company,
                name="x" * 81,
            )

        self.assertFalse(Category.objects.exists())

    def test_renaming_category_recomputes_normalized_name(self):
        category = Category.objects.create(company=self.company, name="Cervejas")

        category.name = "  Porções  "
        category.save(update_fields=["name"])
        category.refresh_from_db()

        self.assertEqual(category.name, "Porções")
        self.assertEqual(category.normalized_name, "porcoes")

    def test_existing_category_cannot_be_moved_to_another_company(self):
        category = Category.objects.create(
            company=self.company,
            name="Cervejas",
        )
        other_company = make_company(name="Empresa de destino")

        category.company = other_company
        with self.assertRaisesMessage(ValidationError, "não pode ser alterada"):
            category.save(update_fields=["company"])

        category.refresh_from_db()
        self.assertEqual(category.company, self.company)

    def test_product_cannot_reference_category_from_another_company(self):
        unit = make_unit(company=self.company)
        other_company = make_company(name="Empresa estrangeira")
        foreign_category = resolve_category(
            company=other_company,
            raw_name="Categoria estrangeira",
        )

        with self.assertRaisesMessage(
            ValidationError,
            "categoria da mesma empresa",
        ):
            make_product(
                company=self.company,
                unit=unit,
                category=foreign_category,
            )

        self.assertFalse(Product.objects.exists())

    def test_product_type_choices_remain_exactly_the_existing_three(self):
        self.assertEqual(
            [value for value, _label in Product.PRODUCT_TYPES],
            ["sale", "internal_use", "both"],
        )
