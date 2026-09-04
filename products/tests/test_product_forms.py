from decimal import Decimal

from django.test import TestCase

from products.forms import (
    ProductComponentForm,
    ProductComponentFormSet,
    ProductCreateForm,
)

from .helpers import make_company, make_product, make_unit


class ProductCreateFormTests(TestCase):
    def setUp(self):
        self.company = make_company(name="Empresa principal")
        self.unit = make_unit(company=self.company)

    def test_legacy_payload_receives_new_safe_defaults(self):
        form = ProductCreateForm(
            data={
                "name": "Produto legado",
                "sale_price": "12,50",
                "product_type": "sale",
                "unit": str(self.unit.pk),
                "active": "on",
            },
            company=self.company,
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["inventory_role"], "direct")
        self.assertEqual(form.cleaned_data["sale_form"], "unit")
        self.assertEqual(form.cleaned_data["stock_dimension"], "count")
        self.assertEqual(form.cleaned_data["minimum_quantity"], Decimal("0"))

    def test_input_defaults_to_internal_use_when_legacy_type_is_omitted(self):
        form = ProductCreateForm(
            data={
                "name": "Papel higiênico",
                "sale_price": "0",
                "sale_form": "unit",
                "inventory_role": "input",
                "stock_dimension": "count",
                "product_type": "auto",
            },
            company=self.company,
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["product_type"], "internal_use")

    def test_prepared_product_requires_preparation_mode(self):
        form = ProductCreateForm(
            data={
                "name": "Caipirinha",
                "sale_price": "18",
                "sale_form": "dose",
                "inventory_role": "prepared",
                "stock_dimension": "volume",
                "dose_ml": "50",
            },
            company=self.company,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("preparation_mode", form.errors)

    def test_unit_queryset_is_isolated_by_company(self):
        other_company = make_company(name="Outra empresa")
        foreign_unit = make_unit(company=other_company)
        form = ProductCreateForm(company=self.company)

        self.assertQuerySetEqual(
            form.fields["unit"].queryset,
            [self.unit],
        )
        self.assertNotIn(foreign_unit, form.fields["unit"].queryset)


class ProductComponentFormTests(TestCase):
    def setUp(self):
        self.company = make_company(name="Empresa principal")
        self.unit = make_unit(company=self.company)
        self.volume_input = make_product(
            company=self.company,
            unit=self.unit,
            name="Vodka",
            inventory_role="input",
            stock_dimension="volume",
        )

    def test_valid_component_preserves_informed_values_for_model_normalization(self):
        form = ProductComponentForm(
            data={
                "ingredient": str(self.volume_input.pk),
                "quantity": "0.05",
                "unit": "L",
            },
            company=self.company,
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["quantity"], Decimal("0.05"))
        self.assertEqual(form.cleaned_data["unit"], "L")

    def test_incompatible_unit_is_rejected(self):
        form = ProductComponentForm(
            data={
                "ingredient": str(self.volume_input.pk),
                "quantity": "50",
                "unit": "g",
            },
            company=self.company,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("unit", form.errors)

    def test_foreign_ingredient_is_not_a_valid_choice(self):
        other_company = make_company(name="Outra empresa")
        foreign = make_product(
            company=other_company,
            name="Ingrediente confidencial",
            inventory_role="input",
            stock_dimension="volume",
        )
        form = ProductComponentForm(
            data={
                "ingredient": str(foreign.pk),
                "quantity": "50",
                "unit": "mL",
            },
            company=self.company,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("ingredient", form.errors)

    def test_formset_rejects_duplicate_ingredients(self):
        formset = ProductComponentFormSet(
            data={
                "components-TOTAL_FORMS": "2",
                "components-INITIAL_FORMS": "0",
                "components-MIN_NUM_FORMS": "0",
                "components-MAX_NUM_FORMS": "1000",
                "components-0-ingredient": str(self.volume_input.pk),
                "components-0-quantity": "50",
                "components-0-unit": "mL",
                "components-1-ingredient": str(self.volume_input.pk),
                "components-1-quantity": "100",
                "components-1-unit": "mL",
            },
            prefix="components",
            form_kwargs={"company": self.company},
        )

        self.assertFalse(formset.is_valid())
        self.assertIn("mais de uma vez", str(formset.non_form_errors()))
