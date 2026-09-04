from django.test import TestCase
from django.urls import reverse

from products.models import Product

from .helpers import make_company, make_product, make_user


class ProductCreateRegressionTests(TestCase):
    def setUp(self):
        self.company = make_company(name="Empresa principal")
        self.user = make_user(company=self.company, role="owner")
        self.client.force_login(self.user)
        self.url = reverse("products:product_create")

    def payload(self, **overrides):
        data = {
            "name": "Produto Teste",
            "sale_price": "10,00",
            "sale_form": "unit",
            "inventory_role": "direct",
            "stock_dimension": "count",
            "preparation_mode": "",
            "product_type": "auto",
            "unit": "",
            "unit_description": "",
            "dose_ml": "",
            "portion_g": "",
            "minimum_quantity": "",
            "active": "on",
            "active_present": "1",
            "components-TOTAL_FORMS": "0",
            "components-INITIAL_FORMS": "0",
            "components-MIN_NUM_FORMS": "0",
            "components-MAX_NUM_FORMS": "1000",
        }
        data.update(overrides)
        return data

    def test_minimum_name_price_and_sale_form_create_product(self):
        response = self.client.post(
            self.url,
            {
                "name": "Produto Teste",
                "sale_price": "10,00",
                "sale_form": "unit",
            },
        )

        self.assertEqual(response.status_code, 302)
        product = Product.objects.get(name="Produto Teste")
        self.assertEqual(product.inventory_role, "direct")
        self.assertEqual(product.sale_form, "unit")
        self.assertEqual(product.stock_dimension, "count")
        self.assertIsNone(product.preparation_mode)
        self.assertFalse(product.components.exists())

    def test_dose_without_ml_is_rejected_with_specific_error(self):
        response = self.client.post(
            self.url,
            self.payload(
                name="Dose simples",
                sale_form="dose",
                stock_dimension="volume",
                dose_ml="",
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Informe o volume de cada dose em mL.")
        self.assertFalse(Product.objects.filter(name="Dose simples").exists())

    def test_portion_without_weight_is_rejected_with_specific_error(self):
        response = self.client.post(
            self.url,
            self.payload(
                name="Porção simples",
                sale_form="portion",
                stock_dimension="weight",
                portion_g="",
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Informe o peso de cada porção em gramas.")
        self.assertFalse(Product.objects.filter(name="Porção simples").exists())

    def test_zero_component_rows_are_valid(self):
        response = self.client.post(
            self.url,
            self.payload(name="Sem receita"),
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Product.objects.get(name="Sem receita").components.exists())

    def test_visually_blank_component_row_is_ignored(self):
        response = self.client.post(
            self.url,
            self.payload(
                name="Linha vazia",
                **{
                    "components-TOTAL_FORMS": "1",
                    "components-0-ingredient": "",
                    "components-0-quantity": "",
                    # Reproduz o valor default enviado pela interface antiga.
                    "components-0-unit": "unit",
                },
            ),
        )

        self.assertEqual(response.status_code, 302)
        product = Product.objects.get(name="Linha vazia")
        self.assertFalse(product.components.exists())

    def test_direct_and_input_ignore_hidden_preparation_mode(self):
        for inventory_role in ("direct", "input"):
            with self.subTest(inventory_role=inventory_role):
                response = self.client.post(
                    self.url,
                    self.payload(
                        name=f"Produto {inventory_role}",
                        inventory_role=inventory_role,
                        preparation_mode="on_demand",
                    ),
                )
                self.assertEqual(response.status_code, 302)
                product = Product.objects.get(name=f"Produto {inventory_role}")
                self.assertIsNone(product.preparation_mode)

    def test_prepared_without_mode_shows_specific_error_and_preserves_values(self):
        response = self.client.post(
            self.url,
            self.payload(
                name="Caipirinha incompleta",
                sale_price="18,50",
                sale_form="dose",
                inventory_role="prepared",
                stock_dimension="volume",
                dose_ml="50",
                preparation_mode="",
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Selecione o modo de preparo do produto preparado.",
        )
        self.assertContains(response, 'value="Caipirinha incompleta"')
        self.assertContains(response, 'value="18,50"')
        self.assertContains(response, 'value="dose" selected')
        self.assertIn(
            '<details class="advanced-settings" open>',
            response.content.decode(),
        )
        self.assertFalse(Product.objects.exists())

    def test_ingredient_without_quantity_shows_specific_error(self):
        ingredient = make_product(
            company=self.company,
            name="Vodka",
            inventory_role="input",
            stock_dimension="volume",
        )
        response = self.client.post(
            self.url,
            self.payload(
                name="Drink incompleto",
                inventory_role="prepared",
                preparation_mode="on_demand",
                **{
                    "components-TOTAL_FORMS": "1",
                    "components-0-ingredient": str(ingredient.pk),
                    "components-0-quantity": "",
                    "components-0-unit": "mL",
                },
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Informe a quantidade deste ingrediente.")
        self.assertEqual(
            response.context["component_formset"].forms[0]["ingredient"].value(),
            str(ingredient.pk),
        )
        self.assertIn(
            '<details class="advanced-settings" open>',
            response.content.decode(),
        )
        self.assertFalse(Product.objects.filter(name="Drink incompleto").exists())

    def test_quantity_without_ingredient_shows_specific_error(self):
        response = self.client.post(
            self.url,
            self.payload(
                name="Drink sem ingrediente",
                inventory_role="prepared",
                preparation_mode="on_demand",
                **{
                    "components-TOTAL_FORMS": "1",
                    "components-0-ingredient": "",
                    "components-0-quantity": "50",
                    "components-0-unit": "mL",
                },
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Selecione o ingrediente.")
        self.assertContains(response, 'value="50"')
        self.assertFalse(Product.objects.filter(name="Drink sem ingrediente").exists())

    def test_incompatible_unit_shows_specific_error(self):
        ingredient = make_product(
            company=self.company,
            name="Limão",
            inventory_role="input",
            stock_dimension="count",
        )
        response = self.client.post(
            self.url,
            self.payload(
                name="Drink incompatível",
                inventory_role="prepared",
                preparation_mode="on_demand",
                **{
                    "components-TOTAL_FORMS": "1",
                    "components-0-ingredient": str(ingredient.pk),
                    "components-0-quantity": "50",
                    "components-0-unit": "mL",
                },
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "A unidade é incompatível com a dimensão de estoque do ingrediente.",
        )
        self.assertFalse(Product.objects.filter(name="Drink incompatível").exists())

    def test_invalid_price_shows_field_error_and_preserves_name(self):
        response = self.client.post(
            self.url,
            self.payload(name="Preço inválido", sale_price="abc"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Informe um preço de venda válido.")
        self.assertContains(response, 'value="Preço inválido"')
        self.assertContains(response, "Confira os campos destacados abaixo.")
        self.assertFalse(Product.objects.filter(name="Preço inválido").exists())
