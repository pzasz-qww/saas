from decimal import Decimal

from django.contrib.auth import SESSION_KEY
from django.contrib.auth.models import AnonymousUser, User
from django.test import RequestFactory, TestCase
from django.urls import reverse

from companies.models import Company
from products.models import Product, Unit

from .models import Profile
from .permissions import (
    SUPPORT_COMPANY_SESSION_KEY,
    get_current_company,
)


class SupportModeTests(TestCase):
    password = "senha-segura-123"

    def setUp(self):
        self.company_a = Company.objects.create(name="Praça Kennedy")
        self.company_b = Company.objects.create(name="Bar Aurora")

        unit_a = Unit.objects.create(
            company=self.company_a,
            name="Unidade PK",
            symbol="un-pk",
        )
        unit_b = Unit.objects.create(
            company=self.company_b,
            name="Unidade Aurora",
            symbol="un-aurora",
        )

        self.product_a = Product.objects.create(
            company=self.company_a,
            name="Heineken PK",
            unit=unit_a,
            sale_price=Decimal("12.00"),
        )
        self.product_b = Product.objects.create(
            company=self.company_b,
            name="Coca Aurora",
            unit=unit_b,
            sale_price=Decimal("8.00"),
        )

        self.owner_a = User.objects.create_user(
            username="dono_pk",
            password=self.password,
        )
        self.owner_a_profile = Profile.objects.create(
            user=self.owner_a,
            company=self.company_a,
            role="owner",
        )

        self.owner_b = User.objects.create_user(
            username="dono_aurora",
            password=self.password,
        )
        self.owner_b_profile = Profile.objects.create(
            user=self.owner_b,
            company=self.company_b,
            role="owner",
        )

        self.staff = User.objects.create_user(
            username="suporte_staff",
            password=self.password,
            is_staff=True,
        )
        self.staff_profile = Profile.objects.create(
            user=self.staff,
            company=self.company_a,
            role="owner",
        )

        self.superuser = User.objects.create_superuser(
            username="suporte_superuser",
            email="suporte@example.com",
            password=self.password,
        )
        self.superuser_profile = Profile.objects.create(
            user=self.superuser,
            company=self.company_a,
            role="owner",
        )

        self.request_factory = RequestFactory()

    def request_for(self, user, session=None):
        request = self.request_factory.get("/")
        request.user = user
        request.session = {} if session is None else session
        return request

    def set_client_session(self, **values):
        session = self.client.session
        for key, value in values.items():
            session[key] = value
        session.save()

    def test_get_current_company_is_request_aware_and_never_falls_back_for_support(self):
        anonymous_request = self.request_for(AnonymousUser())
        self.assertIsNone(get_current_company(anonymous_request))

        common_request = self.request_for(
            self.owner_a,
            {SUPPORT_COMPANY_SESSION_KEY: self.company_b.pk},
        )
        self.assertEqual(
            get_current_company(common_request),
            self.company_a,
        )

        staff_without_selection = self.request_for(self.staff)
        self.assertIsNone(get_current_company(staff_without_selection))

        staff_with_selection = self.request_for(
            self.staff,
            {SUPPORT_COMPANY_SESSION_KEY: self.company_b.pk},
        )
        self.assertEqual(
            get_current_company(staff_with_selection),
            self.company_b,
        )

        superuser_with_selection = self.request_for(
            self.superuser,
            {SUPPORT_COMPANY_SESSION_KEY: self.company_a.pk},
        )
        self.assertEqual(
            get_current_company(superuser_with_selection),
            self.company_a,
        )

    def test_common_user_ignores_support_session_and_gets_403_on_all_support_routes(self):
        self.client.force_login(self.owner_a)
        self.set_client_session(
            **{SUPPORT_COMPANY_SESSION_KEY: self.company_a.pk}
        )

        routes = (
            ("get", reverse("accounts:support_companies")),
            (
                "post",
                reverse(
                    "accounts:select_support_company",
                    args=[self.company_b.pk],
                ),
            ),
            ("post", reverse("accounts:clear_support_company")),
        )

        for method, url in routes:
            with self.subTest(method=method, url=url):
                self.set_client_session(
                    **{SUPPORT_COMPANY_SESSION_KEY: self.company_b.pk}
                )
                response = getattr(self.client, method)(url)

                self.assertEqual(response.status_code, 403)
                self.assertTemplateUsed(
                    response,
                    "accounts/support_forbidden.html",
                )
                self.assertNotIn(
                    SUPPORT_COMPANY_SESSION_KEY,
                    self.client.session,
                )

        request = self.request_for(
            self.owner_a,
            dict(self.client.session),
        )
        self.assertEqual(get_current_company(request), self.company_a)

    def test_anonymous_user_is_redirected_from_support_routes(self):
        routes = (
            ("get", reverse("accounts:support_companies")),
            (
                "post",
                reverse(
                    "accounts:select_support_company",
                    args=[self.company_a.pk],
                ),
            ),
            ("post", reverse("accounts:clear_support_company")),
        )

        for method, url in routes:
            with self.subTest(method=method, url=url):
                response = getattr(self.client, method)(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("accounts:login"), response.url)

    def test_support_selector_lists_status_and_marks_current_company(self):
        inactive_company = Company.objects.create(
            name="Bar Inativo",
            active=False,
        )
        self.client.force_login(self.staff)
        self.set_client_session(
            **{SUPPORT_COMPANY_SESSION_KEY: self.company_a.pk}
        )

        response = self.client.get(reverse("accounts:support_companies"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.company_a.name)
        self.assertContains(response, self.company_b.name)
        self.assertContains(response, inactive_company.name)
        self.assertContains(response, "Selecionada")
        self.assertContains(response, "Ativa")
        self.assertContains(response, "Inativa")
        self.assertContains(response, "Administrar esta empresa")
        self.assertContains(response, "Limpar empresa selecionada")

    def test_support_state_changes_require_post_and_inactive_company_is_rejected(self):
        inactive_company = Company.objects.create(
            name="Bar Inativo",
            active=False,
        )
        self.client.force_login(self.staff)
        self.set_client_session(
            **{SUPPORT_COMPANY_SESSION_KEY: self.company_a.pk}
        )

        select_url = reverse(
            "accounts:select_support_company",
            args=[self.company_b.pk],
        )
        clear_url = reverse("accounts:clear_support_company")

        self.assertEqual(self.client.get(select_url).status_code, 405)
        self.assertEqual(self.client.get(clear_url).status_code, 405)
        self.assertEqual(
            self.client.session[SUPPORT_COMPANY_SESSION_KEY],
            self.company_a.pk,
        )

        response = self.client.post(
            reverse(
                "accounts:select_support_company",
                args=[inactive_company.pk],
            )
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            self.client.session[SUPPORT_COMPANY_SESSION_KEY],
            self.company_a.pk,
        )

    def test_staff_and_superuser_without_selection_cannot_open_pdv(self):
        for support_user in (self.staff, self.superuser):
            with self.subTest(username=support_user.username):
                self.client.logout()
                self.client.force_login(support_user)

                response = self.client.get(reverse("orders:pdv"))

                self.assertEqual(response.status_code, 403)
                self.assertTemplateUsed(
                    response,
                    "accounts/company_required.html",
                )
                self.assertContains(
                    response,
                    "Modo suporte",
                    status_code=403,
                )
                self.assertContains(
                    response,
                    "Selecionar empresa",
                    status_code=403,
                )
                self.assertNotContains(
                    response,
                    self.product_a.name,
                    status_code=403,
                )
                self.assertNotContains(
                    response,
                    self.product_b.name,
                    status_code=403,
                )

    def test_staff_and_superuser_can_select_and_switch_isolated_company_data(self):
        profile_companies_before = dict(
            Profile.objects.values_list("pk", "company_id")
        )

        for support_user in (self.staff, self.superuser):
            with self.subTest(username=support_user.username):
                self.client.logout()
                self.client.force_login(support_user)

                response = self.client.post(
                    reverse(
                        "accounts:select_support_company",
                        args=[self.company_a.pk],
                    )
                )

                self.assertRedirects(
                    response,
                    reverse("orders:pdv"),
                    fetch_redirect_response=False,
                )
                self.assertEqual(
                    self.client.session[SUPPORT_COMPANY_SESSION_KEY],
                    self.company_a.pk,
                )

                response = self.client.get(reverse("orders:pdv"))

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["company"], self.company_a)
                self.assertContains(response, self.product_a.name)
                self.assertNotContains(response, self.product_b.name)

                response = self.client.post(
                    reverse(
                        "accounts:select_support_company",
                        args=[self.company_b.pk],
                    )
                )

                self.assertRedirects(
                    response,
                    reverse("orders:pdv"),
                    fetch_redirect_response=False,
                )
                self.assertEqual(
                    self.client.session[SUPPORT_COMPANY_SESSION_KEY],
                    self.company_b.pk,
                )

                response = self.client.get(reverse("orders:pdv"))

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["company"], self.company_b)
                self.assertContains(response, self.product_b.name)
                self.assertNotContains(response, self.product_a.name)
                self.assertEqual(
                    dict(Profile.objects.values_list("pk", "company_id")),
                    profile_companies_before,
                )

    def test_clear_support_company_blocks_operations_and_preserves_login(self):
        self.client.force_login(self.staff)
        self.client.post(
            reverse(
                "accounts:select_support_company",
                args=[self.company_a.pk],
            )
        )

        response = self.client.post(
            reverse("accounts:clear_support_company")
        )

        self.assertRedirects(
            response,
            reverse("accounts:support_companies"),
            fetch_redirect_response=False,
        )
        session = self.client.session
        self.assertNotIn(SUPPORT_COMPANY_SESSION_KEY, session)
        self.assertEqual(session[SESSION_KEY], str(self.staff.pk))

        response = self.client.get(reverse("orders:pdv"))

        self.assertEqual(response.status_code, 403)
        self.assertTrue(response.wsgi_request.user.is_authenticated)

    def test_invalid_or_stale_support_session_is_cleared_without_logging_out(self):
        self.client.force_login(self.superuser)

        for invalid_company_id in ("not-an-id", 999999):
            with self.subTest(company_id=invalid_company_id):
                self.set_client_session(
                    **{
                        SUPPORT_COMPANY_SESSION_KEY:
                            invalid_company_id,
                    }
                )

                response = self.client.get(reverse("orders:pdv"))

                self.assertEqual(response.status_code, 403)
                self.assertNotIn(
                    SUPPORT_COMPANY_SESSION_KEY,
                    self.client.session,
                )
                self.assertEqual(
                    self.client.session[SESSION_KEY],
                    str(self.superuser.pk),
                )
                self.assertTrue(
                    response.wsgi_request.user.is_authenticated
                )

    def test_selected_company_that_becomes_inactive_is_visible_but_blocked(self):
        self.client.force_login(self.superuser)
        self.set_client_session(
            **{SUPPORT_COMPANY_SESSION_KEY: self.company_a.pk}
        )
        self.company_a.active = False
        self.company_a.save(update_fields=["active"])

        response = self.client.get(reverse("orders:pdv"))

        self.assertEqual(response.status_code, 403)
        self.assertContains(
            response,
            "Modo suporte: empresa inativa",
            status_code=403,
        )
        self.assertContains(
            response,
            self.company_a.name,
            status_code=403,
        )
        self.assertEqual(
            self.client.session[SUPPORT_COMPANY_SESSION_KEY],
            self.company_a.pk,
        )

    def test_switch_and_clear_remove_operational_state_but_preserve_auth_session(self):
        self.client.force_login(self.staff)
        self.set_client_session(
            **{
                SUPPORT_COMPANY_SESSION_KEY: self.company_a.pk,
                "pdv_cart": [{"id": self.product_a.pk}],
                "cart_draft": {"table": "Mesa 1"},
                "stock_filters": {"status": "low"},
                "keep_me": "unrelated",
            }
        )

        self.client.post(
            reverse(
                "accounts:select_support_company",
                args=[self.company_b.pk],
            )
        )

        session = self.client.session
        self.assertEqual(
            session[SUPPORT_COMPANY_SESSION_KEY],
            self.company_b.pk,
        )
        self.assertNotIn("pdv_cart", session)
        self.assertNotIn("cart_draft", session)
        self.assertNotIn("stock_filters", session)
        self.assertEqual(session["keep_me"], "unrelated")
        self.assertEqual(session[SESSION_KEY], str(self.staff.pk))

        self.set_client_session(
            order_filters={"status": "sold"},
            report_period="today",
        )
        self.client.post(reverse("accounts:clear_support_company"))

        session = self.client.session
        self.assertNotIn(SUPPORT_COMPANY_SESSION_KEY, session)
        self.assertNotIn("order_filters", session)
        self.assertNotIn("report_period", session)
        self.assertEqual(session["keep_me"], "unrelated")
        self.assertEqual(session[SESSION_KEY], str(self.staff.pk))

    def test_switching_support_company_does_not_change_existing_profiles(self):
        profile_companies_before = dict(
            Profile.objects.values_list("pk", "company_id")
        )
        self.client.force_login(self.superuser)

        self.client.post(
            reverse(
                "accounts:select_support_company",
                args=[self.company_b.pk],
            )
        )
        self.client.post(reverse("accounts:clear_support_company"))

        self.assertEqual(
            dict(Profile.objects.values_list("pk", "company_id")),
            profile_companies_before,
        )

    def test_support_employee_creation_uses_selected_company(self):
        self.client.force_login(self.staff)
        self.client.post(
            reverse(
                "accounts:select_support_company",
                args=[self.company_b.pk],
            )
        )

        response = self.client.post(
            reverse("accounts:people_management"),
            {
                "action": "create_employee",
                "first_name": "Caixa Aurora",
                "username": "caixa_aurora_suporte",
                "password": "senha-inicial-123",
                "role": "cashier",
                "company": self.company_a.pk,
                "company_id": self.company_a.pk,
            },
        )

        self.assertRedirects(
            response,
            reverse("accounts:people_management"),
            fetch_redirect_response=False,
        )
        employee = User.objects.get(username="caixa_aurora_suporte")
        employee_profile = Profile.objects.get(user=employee)

        self.assertEqual(employee_profile.company, self.company_b)

        self.staff_profile.refresh_from_db()
        self.owner_a_profile.refresh_from_db()
        self.owner_b_profile.refresh_from_db()
        self.assertEqual(self.staff_profile.company, self.company_a)
        self.assertEqual(self.owner_a_profile.company, self.company_a)
        self.assertEqual(self.owner_b_profile.company, self.company_b)

    def test_common_user_topbar_never_shows_support_controls(self):
        self.client.force_login(self.owner_a)

        response = self.client.get(reverse("orders:pdv"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"Empresa: <strong>{self.company_a.name}")
        self.assertNotContains(response, "Modo suporte")
        self.assertNotContains(response, "Selecionar empresa")
        self.assertNotContains(response, "Trocar empresa")
        self.assertNotContains(response, "Sair do modo suporte")
        self.assertNotContains(
            response,
            f'href="{reverse("accounts:support_companies")}"',
        )
        self.assertNotContains(
            response,
            f'action="{reverse("accounts:clear_support_company")}"',
        )
