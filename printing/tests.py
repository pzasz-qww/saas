from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.models import Profile
from companies.models import Company


class PrintingTenantGuardTests(TestCase):
    def test_settings_requires_login(self):
        response = self.client.get(reverse("printing:settings"))

        self.assertRedirects(
            response,
            f"{reverse('accounts:login')}?next={reverse('printing:settings')}",
        )

    def test_settings_shows_current_company(self):
        company = Company.objects.create(name="Praça Kennedy")
        user = User.objects.create_user(
            username="dono_pk",
            password="senha-segura",
        )
        Profile.objects.create(user=user, company=company, role="owner")
        self.client.force_login(user)

        response = self.client.get(reverse("printing:settings"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, company.name)
        self.assertContains(response, user.username)

    def test_settings_blocks_user_without_company(self):
        user = User.objects.create_user(
            username="sem_empresa",
            password="senha-segura",
        )
        self.client.force_login(user)

        response = self.client.get(reverse("printing:settings"))

        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, "accounts/company_required.html")
