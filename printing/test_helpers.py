from decimal import Decimal

from django.test import TestCase

from orders.models import Order
from orders.services import approve_order
from orders.tests.helpers import make_company, make_entry, make_order, make_product, make_user

from .models import ItemPrintContext, OrderPrintContext, Printer, PrintSettings
from .services import enqueue_order


class PrintingCase(TestCase):
    def setUp(self):
        self.company = make_company(name="BAR PRAÇA KENNEDY")
        self.user = make_user(company=self.company, role="waiter", username="pedro")
        self.user.first_name = "Pedro"
        self.user.save()
        self.printer = Printer.objects.create(company=self.company, name="Balcão")
        self.settings = PrintSettings.objects.create(company=self.company, default_printer=self.printer, automatic=True)
        self.product = make_product(company=self.company, name="Heineken", sale_price="10.00")
        self.entry = make_entry(product=self.product, quantity="20")

    def sold_order(self):
        order, items = make_order(company=self.company, created_by=self.user, lines=[(self.product, "2", "10.00")])
        order.table_or_tab = "7"
        order.notes = "Entregar na mesa"
        order.save()
        items[0].notes = "Bem gelada"
        items[0].save()
        OrderPrintContext.objects.get_or_create(company=self.company, order_reference=order.pk, defaults={"employee_role": "Garçom", "employee_name": "Pedro"})
        ItemPrintContext.objects.get_or_create(company=self.company, order_reference=order.pk, item_reference=items[0].pk, product_reference=self.product.pk, defaults={"product_name": "Heineken"})
        approve_order(order_id=order.pk, company=self.company, payment_method="pix", user=self.user)
        return Order.objects.select_related("sale", "company").get(pk=order.pk)

    def job(self):
        order = self.sold_order()
        return enqueue_order(order_id=order.pk, company_id=self.company.pk)
