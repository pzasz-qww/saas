from decimal import Decimal

from django.test import TestCase

from products.sale_quantities import (
    PhysicalSaleQuantityError,
    get_physical_consumption,
    get_sale_availability,
)

from .helpers import make_company, make_product, make_unit


D = Decimal


class SaleQuantityConversionTests(TestCase):
    def setUp(self):
        self.company = make_company()
        self.unit = make_unit(company=self.company)

    def product(self, **kwargs):
        return make_product(company=self.company, unit=self.unit, **kwargs)

    def test_unit_consumes_one_physical_unit_per_sale_unit(self):
        product = self.product()

        result = get_physical_consumption(product, D("3"))

        self.assertEqual(result.quantity_per_sale_unit, D("1"))
        self.assertEqual(result.total_quantity, D("3"))
        self.assertEqual(result.base_unit, "unit")

    def test_dose_consumes_millilitres_and_calculates_complete_availability(self):
        product = self.product(
            sale_form="dose",
            stock_dimension="volume",
            dose_ml="50",
        )

        consumption = get_physical_consumption(product, D("2"))
        availability = get_sale_availability(product, D("4500"))

        self.assertEqual(consumption.total_quantity, D("100"))
        self.assertEqual(consumption.base_unit, "mL")
        self.assertEqual(availability.available_sale_quantity, D("90"))
        self.assertEqual(availability.physical_remainder, D("0"))

    def test_portion_reports_only_complete_portions_and_remainder(self):
        product = self.product(
            sale_form="portion",
            stock_dimension="weight",
            portion_g="400",
        )

        consumption = get_physical_consumption(product, D("3"))
        availability = get_sale_availability(product, D("5000"))

        self.assertEqual(consumption.total_quantity, D("1200"))
        self.assertEqual(consumption.base_unit, "g")
        self.assertEqual(availability.available_sale_quantity, D("12"))
        self.assertEqual(availability.physical_remainder, D("200"))

    def test_float_and_invalid_configuration_are_never_silently_accepted(self):
        product = self.product()

        with self.assertRaises(PhysicalSaleQuantityError):
            get_physical_consumption(product, 1.5)

        product.sale_form = "dose"
        product.stock_dimension = "count"
        product.dose_ml = D("50")
        with self.assertRaises(PhysicalSaleQuantityError):
            get_physical_consumption(product, D("1"))
