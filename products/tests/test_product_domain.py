from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from products.models import Product, ProductComponent

from .helpers import make_company, make_product, make_unit


class ProductDomainTests(TestCase):
    def setUp(self):
        self.company = make_company()
        self.unit = make_unit(company=self.company)

    def make_product(self, **overrides):
        return make_product(company=self.company, unit=self.unit, **overrides)

    def test_safe_defaults_preserve_existing_products(self):
        product = self.make_product()

        self.assertEqual(product.inventory_role, "direct")
        self.assertEqual(product.sale_form, "unit")
        self.assertEqual(product.stock_dimension, "count")
        self.assertEqual(product.unit_description, "")
        self.assertIsNone(product.dose_ml)
        self.assertIsNone(product.portion_g)
        self.assertIsNone(product.preparation_mode)

    def test_every_inventory_role_is_supported(self):
        cases = (
            ("direct", None),
            ("input", None),
            ("prepared", "on_demand"),
        )

        for inventory_role, preparation_mode in cases:
            with self.subTest(inventory_role=inventory_role):
                product = self.make_product(
                    name=f"Produto {inventory_role}",
                    inventory_role=inventory_role,
                    preparation_mode=preparation_mode,
                )
                self.assertEqual(product.inventory_role, inventory_role)

    def test_unit_sale_form_accepts_optional_description(self):
        without_description = self.make_product(name="Sem descrição")
        with_description = self.make_product(
            name="Com descrição",
            unit_description="garrafa 600 ml",
        )

        self.assertEqual(without_description.sale_form, "unit")
        self.assertEqual(with_description.unit_description, "garrafa 600 ml")

    def test_dose_is_valid_with_or_without_ml(self):
        without_ml = self.make_product(name="Dose livre", sale_form="dose")
        with_ml = self.make_product(
            name="Dose medida",
            sale_form="dose",
            dose_ml="50.000000",
        )

        self.assertIsNone(without_ml.dose_ml)
        self.assertEqual(with_ml.dose_ml, Decimal("50.000000"))

    def test_portion_is_valid_with_or_without_grams(self):
        without_grams = self.make_product(name="Porção livre", sale_form="portion")
        with_grams = self.make_product(
            name="Porção medida",
            sale_form="portion",
            portion_g="500.000000",
        )

        self.assertIsNone(without_grams.portion_g)
        self.assertEqual(with_grams.portion_g, Decimal("500.000000"))

    def test_every_stock_dimension_is_supported(self):
        for dimension in ("count", "weight", "volume"):
            with self.subTest(dimension=dimension):
                product = self.make_product(
                    name=f"Produto {dimension}",
                    stock_dimension=dimension,
                )
                self.assertEqual(product.stock_dimension, dimension)

    def test_physical_values_must_be_positive_and_finite(self):
        for field_name in ("dose_ml", "portion_g"):
            for invalid_value in ("0", "-0.001", "NaN", "Infinity"):
                with self.subTest(field=field_name, value=invalid_value):
                    with self.assertRaises(ValidationError):
                        self.make_product(
                            name=f"Inválido {field_name} {invalid_value}",
                            **{field_name: invalid_value},
                        )

    def test_prepared_products_require_a_preparation_mode(self):
        with self.assertRaises(ValidationError):
            self.make_product(inventory_role="prepared")

    def test_non_prepared_products_reject_a_preparation_mode(self):
        with self.assertRaises(ValidationError):
            self.make_product(preparation_mode="on_demand")


class ProductComponentTests(TestCase):
    def setUp(self):
        self.company = make_company(name="Empresa principal")
        self.unit = make_unit(company=self.company)
        self.prepared = make_product(
            company=self.company,
            unit=self.unit,
            name="Caipirinha",
            inventory_role="prepared",
            preparation_mode="on_demand",
        )

    def ingredient(self, *, name, dimension, role="input", company=None):
        company = company or self.company
        unit = self.unit if company == self.company else make_unit(company=company)
        return make_product(
            company=company,
            unit=unit,
            name=name,
            inventory_role=role,
            stock_dimension=dimension,
            preparation_mode="on_demand" if role == "prepared" else None,
        )

    def component(self, ingredient, quantity, unit):
        return ProductComponent.objects.create(
            company=self.company,
            product=self.prepared,
            ingredient=ingredient,
            quantity=Decimal(quantity),
            unit=unit,
        )

    def test_product_without_recipe_is_valid(self):
        self.assertFalse(self.prepared.components.exists())

    def test_recipe_with_one_ingredient_is_valid_and_normalized(self):
        vodka = self.ingredient(name="Vodka", dimension="volume")

        component = self.component(vodka, "0.05", "L")

        self.assertEqual(component.quantity, Decimal("50.00"))
        self.assertEqual(component.unit, "mL")

    def test_partial_recipe_is_valid(self):
        vodka = self.ingredient(name="Vodka", dimension="volume")

        self.component(vodka, "50", "mL")

        self.assertQuerySetEqual(
            self.prepared.components.values_list("ingredient__name", flat=True),
            ["Vodka"],
        )

    def test_recipe_with_multiple_dimensions_is_valid(self):
        vodka = self.ingredient(name="Vodka", dimension="volume")
        lemon = self.ingredient(name="Limão", dimension="count")
        syrup = self.ingredient(name="Xarope", dimension="volume")

        self.component(vodka, "50", "mL")
        self.component(lemon, "1", "unit")
        self.component(syrup, "0.020", "L")

        self.assertEqual(self.prepared.components.count(), 3)

    def test_ingredient_from_another_company_is_rejected(self):
        other_company = make_company(name="Outra empresa")
        foreign = self.ingredient(
            company=other_company,
            name="Ingrediente estrangeiro",
            dimension="count",
        )

        with self.assertRaises(ValidationError):
            self.component(foreign, "1", "unit")

        self.assertFalse(ProductComponent.objects.exists())

    def test_product_cannot_be_its_own_ingredient(self):
        with self.assertRaises(ValidationError):
            self.component(self.prepared, "1", "unit")

    def test_component_quantity_must_be_positive(self):
        ingredient = self.ingredient(name="Limão", dimension="count")

        for quantity in ("0", "-1"):
            with self.subTest(quantity=quantity):
                with self.assertRaises(ValidationError):
                    self.component(ingredient, quantity, "unit")

        self.assertFalse(ProductComponent.objects.exists())

    def test_component_unit_must_match_ingredient_dimension(self):
        ingredient = self.ingredient(name="Limão", dimension="count")

        with self.assertRaises(ValidationError):
            self.component(ingredient, "10", "g")

    def test_prepared_product_cannot_be_an_ingredient(self):
        nested = self.ingredient(
            name="Subpreparo",
            dimension="count",
            role="prepared",
        )

        with self.assertRaises(ValidationError):
            self.component(nested, "1", "unit")

    def test_direct_product_can_be_a_basic_ingredient(self):
        vodka = self.ingredient(
            name="Vodka vendida diretamente",
            dimension="volume",
            role="direct",
        )

        component = self.component(vodka, "50", "mL")

        self.assertEqual(component.ingredient, vodka)

    def test_composition_company_and_product_are_immutable(self):
        ingredient = self.ingredient(name="Limão", dimension="count")
        component = self.component(ingredient, "1", "unit")
        other_company = make_company(name="Outra empresa")

        component.company = other_company
        with self.assertRaises(ValidationError):
            component.save()
