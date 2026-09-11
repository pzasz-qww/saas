from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from products.models import ProductComponent
from products.production_services import create_production

from .helpers import make_company, make_entry, make_product, make_user


D = Decimal


class ProductionModelIntegrityTests(TestCase):
    def setUp(self):
        self.company = make_company()
        self.user = make_user(company=self.company, role="owner")
        self.product = make_product(
            company=self.company,
            inventory_role="prepared",
            preparation_mode="pre_portioned",
        )
        self.ingredient = make_product(
            company=self.company,
            inventory_role="input",
            product_type="internal_use",
            stock_dimension="weight",
        )
        ProductComponent.objects.create(
            company=self.company,
            product=self.product,
            ingredient=self.ingredient,
            quantity=D("500"),
            unit="g",
        )
        make_entry(product=self.ingredient, quantity="5000")
        self.result = create_production(
            company=self.company,
            product=self.product,
            planned_quantity=D("10"),
            produced_quantity=D("8"),
            created_by=self.user,
        )

    def test_production_history_cannot_be_edited(self):
        production = self.result.production
        production.planned_quantity = D("20")
        with self.assertRaisesMessage(ValidationError, "não podem ser alterados"):
            production.save()

    def test_consumption_snapshot_cannot_be_edited(self):
        consumption = self.result.production.consumptions.get()
        consumption.actual_quantity = D("4000")
        with self.assertRaisesMessage(ValidationError, "não pode ser alterado"):
            consumption.save()

    def test_output_lot_origin_cannot_be_reassigned(self):
        output = self.result.output_entry
        output.production = None
        with self.assertRaisesMessage(ValidationError, "dados de origem"):
            output.save()

    def test_output_lot_physical_snapshot_cannot_be_edited(self):
        output = self.result.output_entry
        output.input_quantity = D("9")
        output.quantity_added = D("9")
        output.remaining_quantity = D("9")
        with self.assertRaisesMessage(ValidationError, "dados de origem"):
            output.save()
