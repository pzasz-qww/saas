# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_submodules,
)


project_root = Path(SPECPATH).resolve()


def exclude_test_modules(module_name):
    parts = module_name.split(".")
    return not any(
        part == "tests" or part.startswith("test_")
        for part in parts
    )


project_packages = (
    "accounts",
    "companies",
    "products",
    "orders",
    "sales",
    "printing",
    "config",
)

hidden_imports = []
for package_name in project_packages:
    hidden_imports.extend(
        collect_submodules(
            package_name,
            filter=exclude_test_modules,
            on_error="raise",
        )
    )

hidden_imports.extend(
    collect_submodules(
        "whitenoise",
        on_error="raise",
    )
)

hidden_imports.extend(
    [
        "django.db.backends.sqlite3",
        "django.contrib.admin.templatetags.admin_list",
        "django.contrib.admin.templatetags.admin_modify",
        "django.contrib.admin.templatetags.admin_urls",
        "django.contrib.auth.context_processors",
        "django.contrib.messages.context_processors",
        "django.template.context_processors",
        "whitenoise.storage",
    ]
)

datas = [(str(project_root / "templates"), "templates")]
for static_source in (project_root / "static").iterdir():
    if static_source.name != "admin":
        datas.append(
            (str(static_source), f"static/{static_source.name}")
        )

datas.extend(
    collect_data_files(
        "django",
        includes=[
            "**/templates/**/*",
            "**/static/**/*",
            "conf/locale/pt_BR/**/*",
        ],
    )
)

reportlab_datas, reportlab_binaries, reportlab_hidden_imports = collect_all(
    "reportlab"
)
datas.extend(reportlab_datas)
hidden_imports.extend(reportlab_hidden_imports)

a = Analysis(
    [str(project_root / "portable_launcher.py")],
    pathex=[str(project_root)],
    binaries=reportlab_binaries,
    datas=datas,
    hiddenimports=sorted(set(hidden_imports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "gunicorn",
        "psycopg2",
        "tkinter",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PracaPDV",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=str(project_root / "packaging" / "windows_version_info.txt"),
)
