import os
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Profile
from companies.models import Company
from products.models import Product, Unit


PASSWORD_ENV_VAR = "BAR_SAAS_OWNER_PASSWORD"


class CreateCompanyOwnerCommandTests(TestCase):
    password = "Beta-Owner-Password-2026!"

    @classmethod
    def setUpTestData(cls):
        cls.company_a = Company.objects.create(
            name="Empresa A",
            document="DOC-A",
            phone="11999990000",
        )
        cls.owner_a = get_user_model().objects.create_user(
            username="owner_a",
            email="owner.a@example.com",
            password=cls.password,
        )
        cls.profile_a = Profile.objects.create(
            user=cls.owner_a,
            company=cls.company_a,
            role="owner",
        )
        cls.unit_a = Unit.objects.create(
            company=cls.company_a,
            name="Unidade",
            symbol="un-a",
        )
        cls.product_a = Product.objects.create(
            company=cls.company_a,
            name="Produto da Empresa A",
            unit=cls.unit_a,
        )

    def run_command(self, **overrides):
        options = {
            "company": "Empresa B",
            "username": "owner_b",
            "email": "owner.b@example.com",
            "document": "DOC-B",
            "phone": "11888880000",
            "noinput": True,
            "stdout": StringIO(),
        }
        options.update(overrides)

        with patch.dict(
            os.environ,
            {PASSWORD_ENV_VAR: self.password},
            clear=False,
        ):
            call_command("create_company_owner", **options)

        return options["stdout"]

    def assert_company_a_is_unchanged(self):
        self.company_a.refresh_from_db()
        self.owner_a.refresh_from_db()
        self.profile_a.refresh_from_db()
        self.product_a.refresh_from_db()

        self.assertEqual(self.company_a.name, "Empresa A")
        self.assertEqual(self.company_a.document, "DOC-A")
        self.assertEqual(self.owner_a.email, "owner.a@example.com")
        self.assertEqual(self.profile_a.company, self.company_a)
        self.assertEqual(self.profile_a.role, "owner")
        self.assertEqual(self.product_a.company, self.company_a)
        self.assertEqual(self.product_a.name, "Produto da Empresa A")

    def assert_duplicate_was_rolled_back(self):
        self.assertEqual(Company.objects.count(), 1)
        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertEqual(Profile.objects.count(), 1)
        self.assert_company_a_is_unchanged()

    def test_creates_company_normal_owner_and_owner_profile(self):
        stdout = self.run_command()

        company_b = Company.objects.get(name="Empresa B")
        owner_b = get_user_model().objects.get(username="owner_b")
        profile_b = Profile.objects.get(user=owner_b)

        self.assertEqual(company_b.document, "DOC-B")
        self.assertEqual(company_b.phone, "11888880000")
        self.assertTrue(company_b.active)
        self.assertEqual(owner_b.email, "owner.b@example.com")
        self.assertTrue(owner_b.check_password(self.password))
        self.assertFalse(owner_b.is_staff)
        self.assertFalse(owner_b.is_superuser)
        self.assertEqual(profile_b.company, company_b)
        self.assertEqual(profile_b.role, "owner")
        self.assertTrue(profile_b.can_manage_users)
        self.assertTrue(profile_b.can_view_stock)
        self.assertNotIn(self.password, stdout.getvalue())
        self.assertIn("Empresa B", stdout.getvalue())
        self.assertIn("owner_b", stdout.getvalue())
        self.assert_company_a_is_unchanged()

        self.client.force_login(owner_b)
        stock_response = self.client.get(
            reverse("products:stock_dashboard")
        )
        self.assertEqual(stock_response.status_code, 200)
        self.assertNotContains(stock_response, self.product_a.name)

    def test_rejects_duplicate_company_name_case_insensitively(self):
        with self.assertRaisesMessage(CommandError, "empresa com esse nome"):
            self.run_command(company="empresa a")

        self.assert_duplicate_was_rolled_back()

    def test_rejects_duplicate_document_case_insensitively(self):
        with self.assertRaisesMessage(CommandError, "empresa com esse documento"):
            self.run_command(document="doc-a")

        self.assert_duplicate_was_rolled_back()

    def test_rejects_duplicate_username_case_insensitively(self):
        with self.assertRaisesMessage(CommandError, "usuário com esse nome"):
            self.run_command(username="OWNER_A")

        self.assert_duplicate_was_rolled_back()

    def test_rejects_duplicate_email_case_insensitively(self):
        with self.assertRaisesMessage(CommandError, "usuário com esse e-mail"):
            self.run_command(email="OWNER.A@EXAMPLE.COM")

        self.assert_duplicate_was_rolled_back()

    def test_rejects_invalid_email_without_writing(self):
        with self.assertRaisesMessage(CommandError, "e-mail válido"):
            self.run_command(email="email-invalido")

        self.assert_duplicate_was_rolled_back()

    @override_settings(
        AUTH_PASSWORD_VALIDATORS=[
            {
                "NAME": (
                    "django.contrib.auth.password_validation."
                    "MinimumLengthValidator"
                ),
                "OPTIONS": {"min_length": 12},
            }
        ]
    )
    def test_rejects_password_that_fails_django_validation(self):
        with patch.dict(
            os.environ,
            {PASSWORD_ENV_VAR: "curta"},
            clear=False,
        ):
            with self.assertRaisesMessage(CommandError, "requisitos"):
                call_command(
                    "create_company_owner",
                    company="Empresa B",
                    username="owner_b",
                    email="owner.b@example.com",
                    noinput=True,
                )

        self.assert_duplicate_was_rolled_back()

    def test_noinput_requires_password_environment_variable(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesMessage(CommandError, PASSWORD_ENV_VAR):
                call_command(
                    "create_company_owner",
                    company="Empresa B",
                    username="owner_b",
                    email="owner.b@example.com",
                    noinput=True,
                )

        self.assert_duplicate_was_rolled_back()

    def test_prompt_requires_matching_password_confirmation(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch(
                "companies.management.commands.create_company_owner.getpass.getpass",
                side_effect=[self.password, "senha-diferente"],
            ):
                with self.assertRaisesMessage(CommandError, "não coincidem"):
                    call_command(
                        "create_company_owner",
                        company="Empresa B",
                        username="owner_b",
                        email="owner.b@example.com",
                    )

        self.assert_duplicate_was_rolled_back()
