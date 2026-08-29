from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import Profile
from companies.models import Company
import portable_launcher


class FirstRunOwnerTests(TestCase):
    password = "Portable-Owner-Password-2026!"

    def test_creates_company_and_owner_from_first_run_prompt(self):
        logger = Mock()

        with (
            patch(
                "builtins.input",
                side_effect=[
                    "Bar Portátil",
                    "proprietario",
                    "proprietario@example.com",
                ],
            ),
            patch(
                "companies.management.commands.create_company_owner."
                "getpass.getpass",
                side_effect=[self.password, self.password],
            ),
        ):
            portable_launcher.create_initial_owner_if_needed(logger)

        company = Company.objects.get(name="Bar Portátil")
        owner = get_user_model().objects.get(username="proprietario")
        profile = Profile.objects.get(user=owner)

        self.assertEqual(profile.company, company)
        self.assertEqual(profile.role, "owner")
        self.assertTrue(owner.check_password(self.password))
        logger.info.assert_called_once()

    def test_smoke_test_can_skip_first_run_prompt(self):
        portable_launcher.create_initial_owner_if_needed(Mock(), skip=True)

        self.assertFalse(get_user_model().objects.exists())
        self.assertFalse(Company.objects.exists())
