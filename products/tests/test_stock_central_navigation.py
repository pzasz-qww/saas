from django.test import TestCase
from django.urls import reverse

from accounts.models import Profile

from .helpers import make_company, make_product, make_unit, make_user


class StockCentralNavigationTests(TestCase):
    def setUp(self):
        self.company = make_company(name="Empresa da Central")
        self.other_company = make_company(name="Empresa Vizinha")
        self.user = make_user(
            company=self.company,
            role="waiter",
            username="operador-central",
        )
        self.profile = Profile.objects.get(user=self.user)
        self.client.force_login(self.user)

    def set_stock_permissions(self, *, view=False, create=False, adjust=False):
        self.profile.can_view_stock = view
        self.profile.can_create_stock_entry = create
        self.profile.can_adjust_stock = adjust
        self.profile.save(
            update_fields=[
                "can_view_stock",
                "can_create_stock_entry",
                "can_adjust_stock",
            ]
        )

    def test_authorized_user_sees_only_stock_central_in_main_navigation(self):
        self.set_stock_permissions(view=True, create=True, adjust=True)

        response = self.client.get(reverse("orders:pdv"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'href="{reverse("products:stock_dashboard")}"',
            count=1,
        )
        self.assertContains(response, ">Estoque<", html=False)
        for url_name in (
            "stock_entry_create",
            "stock_count_adjust",
            "product_create",
            "shopping_list",
            "stock_report_pdf",
        ):
            with self.subTest(url_name=url_name):
                self.assertNotContains(
                    response,
                    f'href="{reverse(f"products:{url_name}")}"',
                )

    def test_user_without_stock_access_does_not_see_central_or_open_it(self):
        response = self.client.get(reverse("orders:pdv"))

        self.assertNotContains(
            response,
            f'href="{reverse("products:stock_dashboard")}"',
        )

        central_response = self.client.get(reverse("products:stock_dashboard"))
        self.assertRedirects(central_response, reverse("orders:pdv"))

    def test_owner_sees_every_existing_action_with_named_urls(self):
        owner = make_user(
            company=self.company,
            role="owner",
            username="dono-central",
        )
        self.client.force_login(owner)

        response = self.client.get(reverse("products:stock_dashboard"))

        expected_actions = {
            "entry": "stock_entry_create",
            "count": "stock_count_adjust",
            "product": "product_create",
            "shopping": "shopping_list",
            "pdf": "stock_report_pdf",
        }
        for action, url_name in expected_actions.items():
            with self.subTest(action=action):
                self.assertContains(response, f'data-stock-action="{action}"')
                self.assertContains(
                    response,
                    f'href="{reverse(f"products:{url_name}")}"',
                )

        content = response.content.decode()
        self.assertLess(
            content.index('class="stock-quick-actions"'),
            content.index('class="filters-card"'),
        )

    def test_view_only_user_sees_only_actions_allowed_by_destination_views(self):
        self.set_stock_permissions(view=True)

        response = self.client.get(reverse("products:stock_dashboard"))

        self.assertContains(response, 'data-stock-action="shopping"')
        self.assertContains(response, 'data-stock-action="pdf"')
        self.assertNotContains(response, 'data-stock-action="entry"')
        self.assertNotContains(response, 'data-stock-action="count"')
        self.assertNotContains(response, 'data-stock-action="product"')

    def test_hidden_actions_remain_protected_by_backend_views(self):
        self.set_stock_permissions(view=True)

        central_response = self.client.get(reverse("products:stock_dashboard"))
        self.assertNotContains(central_response, 'data-stock-action="entry"')
        self.assertNotContains(central_response, 'data-stock-action="count"')
        self.assertNotContains(central_response, 'data-stock-action="product"')

        for url_name in (
            "stock_entry_create",
            "stock_count_adjust",
            "product_create",
        ):
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(f"products:{url_name}"))
                self.assertRedirects(
                    response,
                    reverse("products:stock_dashboard"),
                )

    def test_central_does_not_mix_products_from_different_companies(self):
        self.set_stock_permissions(view=True)
        local_product = make_product(
            company=self.company,
            name="Produto da empresa atual",
        )
        foreign_product = make_product(
            company=self.other_company,
            name="Produto confidencial vizinho",
        )

        response = self.client.get(reverse("products:stock_dashboard"))

        self.assertContains(response, local_product.name)
        self.assertNotContains(response, foreign_product.name)

    def test_operational_pages_return_to_central_when_stock_is_visible(self):
        self.set_stock_permissions(view=True, create=True, adjust=True)
        make_unit(company=self.company, name="Unidade operacional")

        for url_name in (
            "stock_entry_create",
            "stock_count_adjust",
            "product_create",
            "shopping_list",
        ):
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(f"products:{url_name}"))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Voltar para o estoque")
                self.assertContains(
                    response,
                    f'href="{reverse("products:stock_dashboard")}"',
                )

    def test_other_main_navigation_items_keep_their_own_permissions(self):
        self.set_stock_permissions(view=True)

        response = self.client.get(reverse("orders:pdv"))

        self.assertContains(response, f'href="{reverse("orders:pdv")}"')
        self.assertContains(
            response,
            f'href="{reverse("products:stock_dashboard")}"',
        )
        self.assertNotContains(
            response,
            f'href="{reverse("orders:orders_panel")}"',
        )
        self.assertNotContains(
            response,
            f'href="{reverse("accounts:people_management")}"',
        )
