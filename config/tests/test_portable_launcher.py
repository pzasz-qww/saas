import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import portable_launcher


class PortableLauncherTests(TestCase):
    def test_prepares_expected_runtime_directories(self):
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)

            paths = portable_launcher.prepare_directories(root)

            self.assertEqual(set(paths), set(portable_launcher.DIRECTORY_NAMES))
            self.assertTrue(all(path.is_dir() for path in paths.values()))

    def test_finds_future_app_directory_layout(self):
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            application_root = root / "app"
            (application_root / "config").mkdir(parents=True)
            (application_root / "manage.py").touch()
            (application_root / "config" / "wsgi.py").touch()

            self.assertEqual(
                portable_launcher.find_application_root(root),
                application_root,
            )

    def test_frozen_runtime_uses_executable_directory_for_data(self):
        with TemporaryDirectory() as temporary_directory:
            executable_path = Path(temporary_directory) / "PracaPDV.exe"
            with (
                patch.object(
                    portable_launcher,
                    "is_frozen_application",
                    return_value=True,
                ),
                patch.object(
                    portable_launcher.sys,
                    "executable",
                    str(executable_path),
                ),
            ):
                self.assertEqual(
                    portable_launcher.get_portable_root(),
                    executable_path.parent.resolve(),
                )

    def test_frozen_runtime_uses_internal_bundle_for_resources(self):
        with TemporaryDirectory() as temporary_directory:
            bundle_root = Path(temporary_directory)
            with (
                patch.object(
                    portable_launcher,
                    "is_frozen_application",
                    return_value=True,
                ),
                patch.object(
                    portable_launcher.sys,
                    "_MEIPASS",
                    str(bundle_root),
                    create=True,
                ),
            ):
                self.assertEqual(
                    portable_launcher.get_application_root(Path("ignored")),
                    bundle_root.resolve(),
                )

    def test_persists_secret_key_between_starts(self):
        with TemporaryDirectory() as temporary_directory:
            config_directory = Path(temporary_directory)
            with patch.dict(os.environ, {}, clear=True):
                first_key = portable_launcher.ensure_secret_key(
                    config_directory
                )
                second_key = portable_launcher.ensure_secret_key(
                    config_directory
                )

            self.assertEqual(first_key, second_key)
            self.assertGreaterEqual(len(first_key), 50)

    def test_environment_file_does_not_override_existing_value(self):
        with TemporaryDirectory() as temporary_directory:
            environment_path = Path(temporary_directory) / "portable.env"
            environment_path.write_text(
                "PORTABLE_PORT=9000\nPORTABLE_OPEN_BROWSER=false\n",
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {"PORTABLE_PORT": "8100"},
                clear=True,
            ):
                portable_launcher.load_environment_file(environment_path)
                self.assertEqual(os.environ["PORTABLE_PORT"], "8100")
                self.assertEqual(
                    os.environ["PORTABLE_OPEN_BROWSER"], "false"
                )

    def test_lan_address_filter_excludes_loopback_and_link_local(self):
        self.assertFalse(
            portable_launcher._is_usable_lan_address("127.0.0.1")
        )
        self.assertFalse(
            portable_launcher._is_usable_lan_address("169.254.10.20")
        )
        self.assertTrue(
            portable_launcher._is_usable_lan_address("192.168.1.20")
        )
