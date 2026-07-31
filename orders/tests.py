import json
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.models import Profile
from companies.models import Company
from orders.models import Order, OrderItem
from products.models import Product, StockEntry, StockMovement, Unit
from sales.models import Sale


class OrderTenantIsolationTests(TestCase):
    def setUp(self):
        self.company_a = Company.objects.create(name="Praça Kennedy")
        self.company_b = Company.objects.create(name="Bar Aurora")
        self.user_a = User.objects.create_user(
            username="dono_pk",
            password="senha-segura",
        )
        self.user_b = User.objects.create_user(
            username="dono_aurora",
            password="senha-segura",
        )
        Profile.objects.create(
            user=self.user_a,
            company=self.company_a,
            role="owner",
        )
        Profile.objects.create(
            user=self.user_b,
            company=self.company_b,
            role="owner",
        )

        self.unit_a = Unit.objects.create(
            company=self.company_a,
            name="Unidade",
            symbol="un-pk",
        )
        self.unit_b = Unit.objects.create(
            company=self.company_b,
            name="Unidade",
            symbol="un-aurora",
        )
        self.product_a = Product.objects.create(
            company=self.company_a,
            name="Heineken PK",
            unit=self.unit_a,
            sale_price=Decimal("12.00"),
        )
        self.product_b = Product.objects.create(
            company=self.company_b,
            name="Coca Aurora",
            unit=self.unit_b,
            sale_price=Decimal("8.00"),
        )
        StockEntry.objects.create(
            company=self.company_a,
            product=self.product_a,
            total_cost=Decimal("50.00"),
            quantity_added=Decimal("20.00"),
        )
        self.entry_b = StockEntry.objects.create(
            company=self.company_b,
            product=self.product_b,
            total_cost=Decimal("40.00"),
            quantity_added=Decimal("20.00"),
        )

        self.order_a = self.create_order(
            self.company_a,
            self.user_a,
            self.product_a,
            "Mesa PK",
        )
        self.order_b_pre_sale = self.create_order(
            self.company_b,
            self.user_b,
            self.product_b,
            "Mesa Aurora pré-venda",
        )
        self.order_b_for_delivery = self.create_paid_order("Mesa Aurora entrega")
        self.order_b_for_return = self.create_paid_order("Mesa Aurora retorno")
        self.order_b_for_discard = self.create_paid_order("Mesa Aurora descarte")

        self.client.force_login(self.user_a)

    @staticmethod
    def create_order(company, user, product, table):
        order = Order.objects.create(
            company=company,
            table_or_tab=table,
            created_by=user,
        )
        OrderItem.objects.create(
            order=order,
            company=company,
            product=product,
            quantity=Decimal("1.00"),
        )
        return order

    def create_paid_order(self, table):
        order = self.create_order(
            self.company_b,
            self.user_b,
            self.product_b,
            table,
        )
        order.approve(payment_method="pix", user=self.user_b)
        order.refresh_from_db()
        return order

    def assert_order_unchanged(self, order, expected_status):
        order.refresh_from_db()
        self.assertEqual(order.status, expected_status)

    def test_pdv_lists_only_current_company_products(self):
        response = self.client.get(reverse("orders:pdv"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Heineken PK")
        self.assertNotContains(response, "Coca Aurora")

    def test_orders_panel_lists_only_current_company_orders(self):
        response = self.client.get(reverse("orders:orders_panel"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mesa PK")
        self.assertNotContains(response, "Mesa Aurora pré-venda")
        self.assertNotContains(response, "Mesa Aurora entrega")

    def test_order_detail_from_another_company_returns_404(self):
        response = self.client.get(
            reverse(
                "orders:order_detail",
                args=[self.order_b_pre_sale.pk],
            )
        )

        self.assertEqual(response.status_code, 404)
        self.assertNotContains(
            response,
            "Mesa Aurora pré-venda",
            status_code=404,
        )

    def test_legacy_cross_company_item_is_not_displayed_or_searchable(self):
        foreign_item = self.order_b_pre_sale.items.get()
        OrderItem.objects.filter(pk=foreign_item.pk).update(
            order=self.order_a
        )

        detail_response = self.client.get(
            reverse("orders:order_detail", args=[self.order_a.pk])
        )
        search_response = self.client.get(
            reverse("orders:orders_panel"),
            {"q": "Coca Aurora"},
        )

        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, "Heineken PK")
        self.assertNotContains(detail_response, "Coca Aurora")
        self.assertEqual(search_response.status_code, 200)
        self.assertNotContains(search_response, "Mesa PK")

    def test_approve_order_from_another_company_does_not_create_sale(self):
        initial_sales = Sale.objects.count()
        initial_movements = StockMovement.objects.count()

        response = self.client.post(
            reverse(
                "orders:approve_order",
                args=[self.order_b_pre_sale.pk, "pix"],
            )
        )

        self.assertEqual(response.status_code, 404)
        self.assert_order_unchanged(self.order_b_pre_sale, "pre_sale")
        self.assertEqual(Sale.objects.count(), initial_sales)
        self.assertEqual(StockMovement.objects.count(), initial_movements)

    def test_cancel_order_from_another_company_does_not_change_status(self):
        response = self.client.post(
            reverse(
                "orders:cancel_order",
                args=[self.order_b_pre_sale.pk],
            )
        )

        self.assertEqual(response.status_code, 404)
        self.assert_order_unchanged(self.order_b_pre_sale, "pre_sale")

    def test_mark_delivered_from_another_company_does_not_change_status(self):
        response = self.client.post(
            reverse(
                "orders:mark_order_delivered",
                args=[self.order_b_for_delivery.pk],
            )
        )

        self.assertEqual(response.status_code, 404)
        self.assert_order_unchanged(self.order_b_for_delivery, "sold")

    def test_cancel_paid_order_from_another_company_does_not_return_stock(self):
        self.entry_b.refresh_from_db()
        initial_quantity = self.entry_b.remaining_quantity
        initial_movements = StockMovement.objects.count()
        sale = self.order_b_for_return.sale

        response = self.client.post(
            reverse(
                "orders:cancel_paid_order_with_stock_return",
                args=[self.order_b_for_return.pk],
            )
        )

        self.assertEqual(response.status_code, 404)
        self.assert_order_unchanged(self.order_b_for_return, "sold")
        sale.refresh_from_db()
        self.entry_b.refresh_from_db()
        self.assertEqual(sale.status, "active")
        self.assertEqual(self.entry_b.remaining_quantity, initial_quantity)
        self.assertEqual(StockMovement.objects.count(), initial_movements)

    def test_discard_paid_order_from_another_company_does_not_change_sale(self):
        sale = self.order_b_for_discard.sale

        response = self.client.post(
            reverse(
                "orders:discard_paid_order",
                args=[self.order_b_for_discard.pk],
            )
        )

        self.assertEqual(response.status_code, 404)
        self.assert_order_unchanged(self.order_b_for_discard, "sold")
        sale.refresh_from_db()
        self.assertEqual(sale.status, "active")

    def test_cross_company_product_in_cart_does_not_leave_orphan_order(self):
        initial_orders = Order.objects.filter(company=self.company_a).count()

        response = self.client.post(
            reverse("orders:pdv"),
            {
                "table_or_tab": "Tentativa cruzada",
                "cart_data": json.dumps(
                    [{"id": self.product_b.pk, "quantity": 1}]
                ),
            },
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            Order.objects.filter(company=self.company_a).count(),
            initial_orders,
        )
        self.assertFalse(
            Order.objects.filter(table_or_tab="Tentativa cruzada").exists()
        )

    def test_non_positive_or_invalid_cart_quantity_is_rejected(self):
        initial_orders = Order.objects.filter(company=self.company_a).count()

        for quantity in ("-1", "0", "NaN", "quantidade-inválida"):
            with self.subTest(quantity=quantity):
                response = self.client.post(
                    reverse("orders:pdv"),
                    {
                        "table_or_tab": "Quantidade inválida",
                        "cart_data": json.dumps(
                            [{
                                "id": self.product_a.pk,
                                "quantity": quantity,
                            }]
                        ),
                    },
                )

                self.assertRedirects(response, reverse("orders:pdv"))
                self.assertEqual(
                    Order.objects.filter(company=self.company_a).count(),
                    initial_orders,
                )

    def test_invalid_payment_method_is_rejected(self):
        initial_sales = Sale.objects.count()

        response = self.client.post(
            reverse(
                "orders:approve_order",
                args=[self.order_a.pk, "metodo-forjado"],
            )
        )

        self.assertRedirects(
            response,
            reverse("orders:order_detail", args=[self.order_a.pk]),
        )
        self.assert_order_unchanged(self.order_a, "pre_sale")
        self.assertEqual(Sale.objects.count(), initial_sales)

    def test_order_item_model_rejects_product_from_another_company(self):
        with self.assertRaises(ValidationError):
            OrderItem.objects.create(
                order=self.order_a,
                company=self.company_a,
                product=self.product_b,
                quantity=Decimal("1.00"),
            )

    def test_order_item_model_rejects_non_positive_quantity(self):
        with self.assertRaises(ValidationError):
            OrderItem.objects.create(
                order=self.order_a,
                company=self.company_a,
                product=self.product_a,
                quantity=Decimal("-1.00"),
            )

    def test_order_model_rejects_invalid_payment_method(self):
        with self.assertRaises(ValidationError):
            self.order_a.approve(
                payment_method="metodo-forjado",
                user=self.user_a,
            )

        self.assert_order_unchanged(self.order_a, "pre_sale")
