from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from products.models import ProductComponent
from products.recipe_services import get_products_availability

from .helpers import make_company, make_entry, make_product, make_user


class PdvOperationalSearchTests(TestCase):
    def setUp(self):
        self.company = make_company(name="Empresa da pesquisa")
        self.user = make_user(company=self.company)
        self.client.force_login(self.user)
        self.url = reverse("orders:pdv")

    def test_search_metadata_covers_name_partial_and_category(self):
        make_product(
            company=self.company,
            name="Heineken Zero",
            category_name="Cervejas",
        )
        make_product(
            company=self.company,
            name="Black Label",
            category_name="Whisky",
        )

        response = self.client.get(self.url)

        self.assertContains(response, 'id="product_search"', html=False)
        self.assertContains(response, "Buscar produto")
        self.assertContains(response, 'data-search="heineken zero cervejas"', html=False)
        self.assertContains(response, 'data-search="black label whisky"', html=False)
        self.assertContains(response, 'data-category-filter="Cervejas"', html=False)
        self.assertContains(response, 'data-category-filter="Whisky"', html=False)

    def test_search_and_category_combination_and_empty_state_are_client_side(self):
        script = Path(settings.BASE_DIR, "static", "js", "pdv.js").read_text(
            encoding="utf-8"
        )
        response = self.client.get(self.url)

        self.assertIn("includes(query)", script)
        self.assertIn("matchesSearch && matchesCategory", script)
        self.assertIn("Nenhum produto encontrado para", script)
        self.assertIn("Nenhum produto encontrado nesta categoria", script)
        self.assertContains(response, "Limpar filtros")

    def test_search_never_renders_products_or_categories_from_another_company(self):
        foreign_company = make_company(name="Empresa externa da pesquisa")
        foreign_product = make_product(
            company=foreign_company,
            name="Produto sigiloso",
            category_name="Categoria sigilosa",
        )

        response = self.client.get(self.url)

        self.assertNotContains(response, foreign_product.name)
        self.assertNotContains(response, "Categoria sigilosa")


class PdvOperationalAvailabilityTests(TestCase):
    def setUp(self):
        self.company = make_company(name="Empresa da disponibilidade")
        self.user = make_user(company=self.company)
        self.client.force_login(self.user)
        self.url = reverse("orders:pdv")

    def product_from_response(self, response, name):
        return next(
            product
            for products in response.context["categories"].values()
            for product in products
            if product.name == name
        )

    def test_direct_dose_and_empty_availability_use_commercial_quantities(self):
        direct = make_product(company=self.company, name="Heineken disponível")
        make_entry(product=direct, quantity="24")
        empty = make_product(company=self.company, name="Heineken esgotada")
        dose = make_product(
            company=self.company,
            name="Red Label dose",
            sale_form="dose",
            stock_dimension="volume",
            dose_ml="50",
        )
        make_entry(product=dose, quantity="4500")
        short_dose = make_product(
            company=self.company,
            name="Dose insuficiente",
            sale_form="dose",
            stock_dimension="volume",
            dose_ml="50",
        )
        make_entry(product=short_dose, quantity="49")

        response = self.client.get(self.url)

        self.assertEqual(
            self.product_from_response(response, direct.name).pdv_available_quantity,
            "24",
        )
        self.assertFalse(
            self.product_from_response(response, empty.name).pdv_is_available
        )
        self.assertEqual(
            self.product_from_response(response, dose.name).pdv_available_quantity,
            "90",
        )
        self.assertFalse(
            self.product_from_response(response, short_dose.name).pdv_is_available
        )
        self.assertContains(response, "<strong>90 doses disponíveis</strong>", html=True)
        self.assertContains(response, "Dose: 50 mL")
        self.assertContains(response, "Esgotado")

    def test_on_demand_uses_components_and_names_the_limiter(self):
        drink = make_product(
            company=self.company,
            name="Caipirinha",
            inventory_role="prepared",
            preparation_mode="on_demand",
        )
        spirit = make_product(
            company=self.company,
            name="Cachaça da casa",
            product_type="internal_use",
            inventory_role="input",
            stock_dimension="volume",
        )
        ProductComponent.objects.create(
            company=self.company,
            product=drink,
            ingredient=spirit,
            quantity=Decimal("50"),
            unit="mL",
        )
        make_entry(product=spirit, quantity="600")

        empty_drink = make_product(
            company=self.company,
            name="Drink sem ingrediente",
            inventory_role="prepared",
            preparation_mode="on_demand",
        )
        empty_ingredient = make_product(
            company=self.company,
            name="Ingrediente zerado",
            product_type="internal_use",
            inventory_role="input",
        )
        ProductComponent.objects.create(
            company=self.company,
            product=empty_drink,
            ingredient=empty_ingredient,
            quantity=Decimal("1"),
            unit="unit",
        )

        response = self.client.get(self.url)

        rendered_drink = self.product_from_response(response, drink.name)
        rendered_empty = self.product_from_response(response, empty_drink.name)
        self.assertEqual(rendered_drink.pdv_available_quantity, "12")
        self.assertTrue(rendered_drink.pdv_is_available)
        self.assertEqual(
            rendered_drink.pdv_availability.limiting_component.ingredient,
            spirit,
        )
        self.assertFalse(rendered_empty.pdv_is_available)
        self.assertContains(response, "<strong>12 disponíveis</strong>", html=True)
        self.assertContains(response, "Limitado por: Cachaça da casa")
        self.assertContains(response, "Sem Ingrediente zerado suficiente.")

    def test_pre_portioned_uses_only_ready_stock_not_production_potential(self):
        ingredient = make_product(
            company=self.company,
            name="Carne insumo",
            product_type="internal_use",
            inventory_role="input",
        )
        make_entry(product=ingredient, quantity="10")
        ready = make_product(
            company=self.company,
            name="Porção com prontas",
            inventory_role="prepared",
            preparation_mode="pre_portioned",
        )
        no_ready = make_product(
            company=self.company,
            name="Porção só com potencial",
            inventory_role="prepared",
            preparation_mode="pre_portioned",
        )
        for product in (ready, no_ready):
            ProductComponent.objects.create(
                company=self.company,
                product=product,
                ingredient=ingredient,
                quantity=Decimal("1"),
                unit="unit",
            )
        make_entry(product=ready, quantity="7")

        response = self.client.get(self.url)

        rendered_ready = self.product_from_response(response, ready.name)
        rendered_no_ready = self.product_from_response(response, no_ready.name)
        self.assertEqual(rendered_ready.pdv_available_quantity, "7")
        self.assertTrue(rendered_ready.pdv_is_available)
        self.assertFalse(rendered_no_ready.pdv_is_available)
        self.assertContains(response, "<strong>7 prontas</strong>", html=True)
        self.assertContains(response, "Nenhuma unidade pronta para venda.")
        self.assertNotContains(response, "Pode preparar")

    def test_batch_availability_has_bounded_queries(self):
        direct = make_product(company=self.company, name="Direto em lote")
        make_entry(product=direct, quantity="3")
        prepared = make_product(
            company=self.company,
            name="Preparado em lote",
            inventory_role="prepared",
            preparation_mode="on_demand",
        )
        ingredient = make_product(
            company=self.company,
            name="Ingrediente em lote",
            product_type="internal_use",
            inventory_role="input",
        )
        ProductComponent.objects.create(
            company=self.company,
            product=prepared,
            ingredient=ingredient,
            quantity=Decimal("1"),
            unit="unit",
        )
        make_entry(product=ingredient, quantity="5")

        with self.assertNumQueries(2):
            batch = get_products_availability(
                [direct, prepared],
                company=self.company,
            )

        self.assertEqual(batch.availability_by_product[direct.pk].available_quantity, 3)
        self.assertEqual(batch.availability_by_product[prepared.pk].available_quantity, 5)

    def test_cross_company_recipe_component_is_never_used(self):
        drink = make_product(
            company=self.company,
            name="Drink com receita corrompida",
            inventory_role="prepared",
            preparation_mode="on_demand",
        )
        foreign_company = make_company(name="Empresa do ingrediente externo")
        foreign_ingredient = make_product(
            company=foreign_company,
            name="Ingrediente externo",
            product_type="internal_use",
            inventory_role="input",
        )
        make_entry(product=foreign_ingredient, quantity="100")
        ProductComponent.objects.bulk_create(
            [
                ProductComponent(
                    company=self.company,
                    product=drink,
                    ingredient=foreign_ingredient,
                    quantity=Decimal("1"),
                    unit="unit",
                )
            ]
        )

        batch = get_products_availability([drink], company=self.company)

        self.assertNotIn(drink.pk, batch.availability_by_product)
        self.assertIn(drink.pk, batch.errors_by_product)


class PdvOperationalCartSourceTests(TestCase):
    def test_cart_enforces_presented_limit_and_keeps_operational_controls(self):
        script = Path(settings.BASE_DIR, "static", "js", "pdv.js").read_text(
            encoding="utf-8"
        )

        self.assertIn("existing.quantity >= product.available", script)
        self.assertIn("item.quantity >= item.available", script)
        self.assertIn("increaseItem", script)
        self.assertIn("decreaseItem", script)
        self.assertIn("removeItem", script)
        self.assertIn("Subtotal", script)
        self.assertIn("cartSubmitButton.disabled", script)
        self.assertNotIn("innerHTML", script)
