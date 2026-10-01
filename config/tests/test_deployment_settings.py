import os
from pathlib import Path
import runpy
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured


SETTINGS_PATH = Path(__file__).resolve().parents[1] / "settings.py"
PROJECT_ROOT = SETTINGS_PATH.parent.parent


class DeploymentSettingsTests(TestCase):
    def load_settings(self, environment):
        with patch.dict(os.environ, environment, clear=True):
            return runpy.run_path(str(SETTINGS_PATH))

    def test_portable_uses_isolated_runtime_paths_and_sqlite(self):
        with TemporaryDirectory() as temporary_directory:
            portable_root = Path(temporary_directory).resolve()
            loaded = self.load_settings(
                {
                    "DEPLOYMENT_MODE": "portable",
                    "PORTABLE_ROOT": str(portable_root),
                    "SECRET_KEY": "p" * 64,
                    "ALLOWED_HOSTS": "localhost,127.0.0.1,192.168.1.20",
                    # O modo portátil não pode herdar o banco cloud.
                    "DATABASE_URL": "postgresql://user:pass@host/cloud",
                    "DEBUG": "true",
                }
            )

            self.assertEqual(loaded["DEPLOYMENT_MODE"], "portable")
            self.assertTrue(loaded["IS_PORTABLE"])
            self.assertFalse(loaded["DEBUG"])
            self.assertEqual(
                loaded["DATABASES"]["default"]["ENGINE"],
                "django.db.backends.sqlite3",
            )
            self.assertEqual(
                loaded["DATABASES"]["default"]["NAME"],
                portable_root / "data" / "db.sqlite3",
            )
            self.assertEqual(loaded["STATIC_ROOT"], portable_root / "static")
            self.assertEqual(loaded["MEDIA_ROOT"], portable_root / "media")
            self.assertEqual(
                loaded["PORTABLE_LOG_DIR"], portable_root / "logs"
            )
            self.assertEqual(
                loaded["PORTABLE_BACKUP_DIR"], portable_root / "backups"
            )
            for directory_name in (
                "data",
                "media",
                "logs",
                "backups",
                "config",
            ):
                self.assertTrue((portable_root / directory_name).is_dir())

    def test_cloud_keeps_postgresql_and_production_security(self):
        loaded = self.load_settings(
            {
                "DEPLOYMENT_MODE": "cloud",
                "SECRET_KEY": "c" * 64,
                "ALLOWED_HOSTS": "pdv.example.com",
                "DATABASE_URL": "postgresql://user:pass@host/cloud",
            }
        )

        self.assertTrue(loaded["IS_PRODUCTION"])
        self.assertFalse(loaded["DEBUG"])
        self.assertEqual(
            loaded["DATABASES"]["default"]["ENGINE"],
            "django.db.backends.postgresql",
        )
        self.assertEqual(loaded["STATIC_ROOT"], PROJECT_ROOT / "staticfiles")
        self.assertTrue(loaded["SECURE_SSL_REDIRECT"])
        self.assertTrue(loaded["SESSION_COOKIE_SECURE"])
        self.assertTrue(loaded["CSRF_COOKIE_SECURE"])

    def test_render_flag_remains_compatible_with_cloud_mode(self):
        loaded = self.load_settings(
            {
                "RENDER": "true",
                "SECRET_KEY": "r" * 64,
                "ALLOWED_HOSTS": "pdv.onrender.com",
                "DATABASE_URL": "postgresql://user:pass@host/cloud",
            }
        )

        self.assertEqual(loaded["DEPLOYMENT_MODE"], "cloud")
        self.assertTrue(loaded["IS_PRODUCTION"])

    def test_render_hostname_configures_host_and_https_csrf_origin(self):
        loaded = self.load_settings(
            {
                "RENDER": "true",
                "RENDER_EXTERNAL_HOSTNAME": "praca-pdv.onrender.com",
                "SECRET_KEY": "r" * 64,
                "DATABASE_URL": "postgresql://user:pass@host/cloud",
            }
        )

        self.assertEqual(loaded["ALLOWED_HOSTS"], ["praca-pdv.onrender.com"])
        self.assertEqual(
            loaded["CSRF_TRUSTED_ORIGINS"],
            ["https://praca-pdv.onrender.com"],
        )

    def test_cloud_requires_an_explicit_or_render_host(self):
        with self.assertRaisesRegex(
            ImproperlyConfigured,
            "ALLOWED_HOSTS ou RENDER_EXTERNAL_HOSTNAME",
        ):
            self.load_settings(
                {
                    "DEPLOYMENT_MODE": "cloud",
                    "SECRET_KEY": "c" * 64,
                    "DATABASE_URL": "postgresql://user:pass@host/cloud",
                }
            )

    def test_portable_rejects_wildcard_host(self):
        with TemporaryDirectory() as temporary_directory:
            with self.assertRaisesRegex(
                ImproperlyConfigured,
                r"não pode usar '\*'",
            ):
                self.load_settings(
                    {
                        "DEPLOYMENT_MODE": "portable",
                        "PORTABLE_ROOT": temporary_directory,
                        "SECRET_KEY": "p" * 64,
                        "ALLOWED_HOSTS": "*",
                    }
                )

    def test_default_mode_remains_development(self):
        loaded = self.load_settings({})

        self.assertEqual(loaded["DEPLOYMENT_MODE"], "development")
        self.assertTrue(loaded["DEBUG"])
        self.assertEqual(
            loaded["DATABASES"]["default"]["NAME"],
            PROJECT_ROOT / "db.sqlite3",
        )
