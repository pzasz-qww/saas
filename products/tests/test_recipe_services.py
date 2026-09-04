from decimal import Decimal

from django.test import TestCase

from products.models import Product, ProductComponent
from products.recipe_services import (
    InvalidOperationalRecipe,
    expand_product_components,
    get_product_availability,
)

from .helpers import make_company, make_entry, make_product, make_unit


D = Decimal


class RecipeServiceTests(TestCase):
    def setUp(self):
        self.company = make_company()
        self.unit = make_unit(company=self.company)
        self.prepared = make_product(
            company=self.company,
            unit=self.unit,
            name="Caipirinha",
            inventory_role="prepared",
            preparation_mode="on_demand",
        )

    def ingredient(self, name, dimension):
        return make_product(
            company=self.company,
            unit=self.unit,
            name=name,
            inventory_role="input",
            product_type="internal_use",
            stock_dimension=dimension,
        )

    def component(self, ingredient, quantity, unit):
        return ProductComponent.objects.create(
            company=self.company,
            product=self.prepared,
            ingredient=ingredient,
            quantity=D(quantity),
            unit=unit,
        )

    def test_expansion_multiplies_every_normalized_component(self):
        spirit = self.ingredient("Cachaça", "volume")
        lemon = self.ingredient("Limão", "weight")
        sugar = self.ingredient("Açúcar", "weight")
        self.component(spirit, "50", "mL")
        self.component(lemon, "80", "g")
        self.component(sugar, "15", "g")

        expanded = expand_product_components(self.prepared, D("3"))
        totals = {
            item.ingredient.name: item.total_quantity for item in expanded
        }

        self.assertEqual(
            totals,
            {"Açúcar": D("45"), "Cachaça": D("150"), "Limão": D("240")},
        )

    def test_simple_availability_is_physical_stock_divided_by_component(self):
        spirit = self.ingredient("Cachaça", "volume")
        self.component(spirit, "50", "mL")
        make_entry(product=spirit, quantity="500")

        availability = get_product_availability(self.prepared)

        self.assertEqual(availability.available_quantity, D("10"))
        self.assertEqual(availability.limiting_component.ingredient, spirit)

    def test_limiting_ingredient_is_the_smallest_complete_yield(self):
        spirit = self.ingredient("Cachaça", "volume")
        lemon = self.ingredient("Limão", "weight")
        sugar = self.ingredient("Açúcar", "weight")
        self.component(spirit, "50", "mL")
        self.component(lemon, "80", "g")
        self.component(sugar, "15", "g")
        make_entry(product=spirit, quantity="1000")
        make_entry(product=lemon, quantity="640")
        make_entry(product=sugar, quantity="450")

        availability = get_product_availability(self.prepared)
        by_name = {
            item.ingredient.name: item.available_quantity
            for item in availability.component_availability
        }

        self.assertEqual(by_name, {"Açúcar": D("30"), "Cachaça": D("20"), "Limão": D("8")})
        self.assertEqual(availability.available_quantity, D("8"))
        self.assertEqual(availability.limiting_component.ingredient, lemon)

    def test_empty_on_demand_recipe_is_explicitly_invalid(self):
        with self.assertRaisesMessage(
            InvalidOperationalRecipe,
            "não possui componentes",
        ):
            get_product_availability(self.prepared)

    def test_inactive_ingredient_invalidates_existing_recipe(self):
        spirit = self.ingredient("Cachaça", "volume")
        self.component(spirit, "50", "mL")
        Product.objects.filter(pk=spirit.pk).update(active=False)

        with self.assertRaisesMessage(InvalidOperationalRecipe, "está inativo"):
            get_product_availability(self.prepared)

    def test_component_uses_physical_quantity_not_ingredient_sale_presentation(self):
        spirit = make_product(
            company=self.company,
            unit=self.unit,
            name="Whisky",
            inventory_role="direct",
            sale_form="dose",
            stock_dimension="volume",
            dose_ml="50",
        )
        self.component(spirit, "0.1", "L")
        portioned_ingredient = make_product(
            company=self.company,
            unit=self.unit,
            name="Carne",
            inventory_role="direct",
            sale_form="portion",
            stock_dimension="weight",
            portion_g="400",
        )
        self.component(portioned_ingredient, "250", "g")

        before = {
            item.ingredient: item
            for item in expand_product_components(self.prepared, D("2"))
        }
        spirit.dose_ml = D("200")
        spirit.save(update_fields=["dose_ml"])
        portioned_ingredient.portion_g = D("800")
        portioned_ingredient.save(update_fields=["portion_g"])
        after = {
            item.ingredient: item
            for item in expand_product_components(self.prepared, D("2"))
        }

        self.assertEqual(before[spirit].quantity_per_sale_unit, D("100"))
        self.assertEqual(before[spirit].total_quantity, D("200"))
        self.assertEqual(after[spirit].total_quantity, D("200"))
        self.assertEqual(before[portioned_ingredient].total_quantity, D("500"))
        self.assertEqual(after[portioned_ingredient].total_quantity, D("500"))

    def test_pre_portioned_product_keeps_own_stock_availability(self):
        pre_portioned = make_product(
            company=self.company,
            unit=self.unit,
            name="Porção pronta",
            inventory_role="prepared",
            preparation_mode="pre_portioned",
        )
        make_entry(product=pre_portioned, quantity="4")

        availability = get_product_availability(pre_portioned)

        self.assertEqual(availability.source, "own_stock")
        self.assertEqual(availability.available_quantity, D("4"))
