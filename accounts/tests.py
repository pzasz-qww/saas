from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser, User
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import RequestFactory, TestCase
from django.urls import reverse

from companies.models import Company

from .models import Profile, StaffRole
from .permissions import (
    SUPPORT_COMPANY_SESSION_KEY,
    get_current_company,
    get_user_company,
)


class CurrentCompanyTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Praça Kennedy")
        self.factory = RequestFactory()

    def request_for(self, user):
        request = self.factory.get("/")
        SessionMiddleware(lambda current_request: None).process_request(request)
        request.session.save()
        request.user = user
        return request

    def test_anonymous_user_has_no_current_company(self):
        self.assertIsNone(get_current_company(self.request_for(AnonymousUser())))

    def test_current_company_comes_from_profile(self):
        user = User.objects.create_user(
            username="dono_pk",
            password="senha-segura",
        )
        Profile.objects.create(
            user=user,
            company=self.company,
            role="owner",
        )

        self.assertEqual(get_current_company(self.request_for(user)), self.company)
        self.assertEqual(get_user_company(user), self.company)

    def test_superuser_without_profile_does_not_receive_first_company(self):
        Company.objects.create(name="Bar Aurora")
        superuser = User.objects.create_superuser(
            username="suporte",
            email="suporte@example.com",
            password="senha-segura",
        )

        self.assertIsNone(get_current_company(self.request_for(superuser)))
        self.assertIsNone(get_user_company(superuser))


class CompanyContextAndGuardTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Praça Kennedy")
        self.owner = User.objects.create_user(
            username="dono_pk",
            password="senha-segura",
        )
        self.owner_profile = Profile.objects.create(
            user=self.owner,
            company=self.company,
            role="owner",
        )

    def test_logged_screen_shows_company_user_and_role(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse("accounts:people_management"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["current_company"], self.company)
        self.assertContains(response, "Empresa:")
        self.assertContains(response, self.company.name)
        self.assertContains(response, "Usuário:")
        self.assertContains(response, self.owner.username)
        self.assertContains(response, "Função:")
        self.assertContains(response, "Dono")
        self.assertNotContains(response, "Modo suporte")

    def test_superuser_with_profile_sees_explicit_support_mode(self):
        superuser = User.objects.create_superuser(
            username="suporte_com_empresa",
            email="suporte@example.com",
            password="senha-segura",
        )
        Profile.objects.create(
            user=superuser,
            company=self.company,
            role="owner",
        )
        self.client.force_login(superuser)

        session = self.client.session
        session[SUPPORT_COMPANY_SESSION_KEY] = self.company.pk
        session.save()

        response = self.client.get(reverse("accounts:people_management"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Modo suporte")
        self.assertContains(response, f"Visualizando: {self.company.name}")
        self.assertTrue(response.context["is_support_mode"])

    def test_staff_user_without_superuser_status_has_no_global_admin_link(self):
        staff_user = User.objects.create_user(
            username="staff_empresa",
            password="senha-segura",
            is_staff=True,
        )
        Profile.objects.create(
            user=staff_user,
            company=self.company,
            role="owner",
        )
        self.client.force_login(staff_user)

        session = self.client.session
        session[SUPPORT_COMPANY_SESSION_KEY] = self.company.pk
        session.save()

        response = self.client.get(reverse("accounts:people_management"))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["menu_permissions"]["can_access_admin"])
        self.assertNotContains(
            response,
            f'href="{reverse("admin:index")}"',
        )

        admin_response = self.client.get(reverse("admin:index"))
        self.assertEqual(admin_response.status_code, 302)
        self.assertIn(reverse("admin:login"), admin_response.url)

    def test_superuser_without_profile_is_blocked_and_operations_are_disabled(self):
        superuser = User.objects.create_superuser(
            username="suporte_sem_empresa",
            email="suporte@example.com",
            password="senha-segura",
        )
        self.client.force_login(superuser)

        response = self.client.get(reverse("accounts:people_management"))

        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, "accounts/company_required.html")
        self.assertContains(
            response,
            "Modo suporte: nenhuma empresa selecionada",
            status_code=403,
        )
        self.assertContains(
            response,
            "Selecione uma empresa para liberar as operações.",
            status_code=403,
        )
        self.assertNotContains(
            response,
            f'href="{reverse("orders:pdv")}"',
            status_code=403,
        )

    def test_login_screen_does_not_render_main_menu(self):
        response = self.client.get(reverse("accounts:login"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'class="app-topbar"')

    def test_inactive_company_keeps_context_visible_but_blocks_operations(self):
        self.company.active = False
        self.company.save(update_fields=["active"])
        self.client.force_login(self.owner)

        response = self.client.get(reverse("accounts:people_management"))

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.context["current_company"], self.company)
        self.assertContains(response, "Empresa inativa", status_code=403)
        self.assertContains(response, self.company.name, status_code=403)
        self.assertContains(
            response,
            "Reative a empresa para liberar as operações.",
            status_code=403,
        )
        self.assertNotContains(
            response,
            f'href="{reverse("orders:pdv")}"',
            status_code=403,
        )


class PeopleManagementIsolationTests(TestCase):
    def setUp(self):
        self.company_a = Company.objects.create(name="Praça Kennedy")
        self.company_b = Company.objects.create(name="Bar Aurora")
        self.owner = User.objects.create_user(
            username="dono_pk",
            password="senha-segura",
        )
        Profile.objects.create(
            user=self.owner,
            company=self.company_a,
            role="owner",
        )
        self.client.force_login(self.owner)

    def test_create_employee_uses_creator_company_and_ignores_posted_company(self):
        response = self.client.post(
            reverse("accounts:people_management"),
            {
                "action": "create_employee",
                "first_name": "Caixa PK",
                "username": "caixa_pk",
                "password": "senha-caixa",
                "role": "cashier",
                "company": self.company_b.pk,
                "company_id": self.company_b.pk,
            },
        )

        self.assertRedirects(
            response,
            reverse("accounts:people_management"),
        )
        employee = User.objects.get(username="caixa_pk")
        employee_profile = Profile.objects.get(user=employee)
        creator_profile = Profile.objects.get(user=self.owner)

        self.assertEqual(employee_profile.company, self.company_a)
        self.assertEqual(creator_profile.company, self.company_a)

    def test_profile_rejects_role_template_from_another_company(self):
        foreign_role = StaffRole.objects.create(
            company=self.company_b,
            name="Função Aurora",
        )
        employee = User.objects.create_user(
            username="funcionario_pk",
            password="senha-segura",
        )

        with self.assertRaises(ValidationError):
            Profile.objects.create(
                user=employee,
                company=self.company_a,
                role="waiter",
                role_template=foreign_role,
            )

    def test_legacy_foreign_role_name_is_not_exposed(self):
        foreign_role = StaffRole.objects.create(
            company=self.company_b,
            name="Função secreta Aurora",
        )
        Profile.objects.filter(user=self.owner).update(
            role_template=foreign_role
        )

        response = self.client.get(reverse("accounts:people_management"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Função secreta Aurora")
        self.assertContains(response, "Dono")

    def test_create_employee_rolls_back_user_when_profile_creation_fails(self):
        with patch(
            "accounts.views.Profile.save",
            side_effect=IntegrityError("profile failure"),
        ):
            response = self.client.post(
                reverse("accounts:people_management"),
                {
                    "action": "create_employee",
                    "first_name": "Sem Perfil",
                    "username": "sem_perfil",
                    "password": "senha-inicial",
                    "role": "waiter",
                },
                follow=True,
            )

        self.assertFalse(User.objects.filter(username="sem_perfil").exists())
        self.assertContains(
            response,
            "Não foi possível criar o membro da equipe.",
        )

    def test_update_profile_cannot_target_another_company(self):
        other_user = User.objects.create_user(
            username="funcionario_aurora",
            password="senha-segura",
            first_name="Nome original",
        )
        other_profile = Profile.objects.create(
            user=other_user,
            company=self.company_b,
            role="waiter",
        )

        response = self.client.post(
            reverse("accounts:people_management"),
            {
                "action": "update_profile",
                "profile_id": other_profile.pk,
                "first_name": "Nome alterado",
                "role": "owner",
                "is_active": "on",
            },
        )

        self.assertEqual(response.status_code, 404)
        other_user.refresh_from_db()
        other_profile.refresh_from_db()
        self.assertEqual(other_user.first_name, "Nome original")
        self.assertEqual(other_profile.role, "waiter")

    def test_update_permissions_cannot_target_another_company(self):
        other_user = User.objects.create_user(
            username="caixa_aurora",
            password="senha-segura",
        )
        other_profile = Profile.objects.create(
            user=other_user,
            company=self.company_b,
            role="waiter",
        )

        response = self.client.post(
            reverse("accounts:people_management"),
            {
                "action": "update_permissions",
                "profile_id": other_profile.pk,
                "can_manage_users": "on",
            },
        )

        self.assertEqual(response.status_code, 404)
        other_profile.refresh_from_db()
        self.assertFalse(other_profile.can_manage_users)
