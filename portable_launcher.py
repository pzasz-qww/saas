"""Inicializador local e portátil do Praça PDV para Windows."""

from __future__ import annotations

import argparse
import http.client
import ipaddress
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import secrets
import socket
import sys
import threading
import time
import webbrowser


APP_VERSION = "Prebeta 3"
DEFAULT_PORT = 8000
READY_TIMEOUT_SECONDS = 30
DIRECTORY_NAMES = ("data", "static", "media", "logs", "backups", "config")


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def find_application_root(portable_root: Path) -> Path:
    """Aceita tanto o repositório atual quanto o futuro layout app/."""
    candidates = (portable_root, portable_root / "app")
    for candidate in candidates:
        if (
            (candidate / "manage.py").is_file()
            and (candidate / "config" / "wsgi.py").is_file()
        ):
            return candidate
    raise FileNotFoundError(
        "Não foi possível localizar manage.py e config/wsgi.py na pasta "
        "do launcher nem em app/."
    )


def is_frozen_application() -> bool:
    return bool(getattr(sys, "frozen", False))


def get_portable_root() -> Path:
    """Retorna a pasta gravável ao lado do script ou do executável."""
    if is_frozen_application():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def get_application_root(portable_root: Path) -> Path:
    """Retorna recursos internos do bundle ou o código-fonte local."""
    if is_frozen_application():
        bundle_root = getattr(sys, "_MEIPASS", None)
        if not bundle_root:
            raise RuntimeError(
                "O executável não informou a pasta interna de recursos."
            )
        return Path(bundle_root).resolve()
    return find_application_root(portable_root)


def prepare_directories(portable_root: Path) -> dict[str, Path]:
    paths = {
        name: portable_root / name
        for name in DIRECTORY_NAMES
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def load_environment_file(path: Path) -> None:
    """Carrega um arquivo KEY=VALUE simples sem dependências adicionais."""
    if not path.is_file():
        return

    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(),
        start=1,
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(
                f"Linha inválida em {path.name}:{line_number}. Use CHAVE=VALOR."
            )
        name, value = line.split("=", 1)
        name = name.strip()
        if not name:
            raise ValueError(
                f"Chave vazia em {path.name}:{line_number}."
            )
        os.environ.setdefault(name, value.strip().strip('"').strip("'"))


def configure_logging(log_directory: Path) -> logging.Logger:
    logger = logging.getLogger("praca_pdv.portable")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    file_handler = RotatingFileHandler(
        log_directory / "portable.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger


def ensure_secret_key(config_directory: Path) -> str:
    configured_key = os.getenv("SECRET_KEY", "").strip()
    if len(configured_key) >= 50 and not configured_key.startswith(
        "django-insecure-"
    ):
        return configured_key

    secret_path = config_directory / "portable_secret_key.txt"
    if secret_path.is_file():
        persisted_key = secret_path.read_text(encoding="utf-8").strip()
        if len(persisted_key) < 50:
            raise ValueError(
                f"A chave persistente em {secret_path} está inválida."
            )
        return persisted_key

    persisted_key = secrets.token_urlsafe(48)
    secret_path.write_text(persisted_key + "\n", encoding="utf-8")
    return persisted_key


def _is_usable_lan_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return (
        address.version == 4
        and not address.is_loopback
        and not address.is_link_local
        and not address.is_multicast
        and not address.is_unspecified
    )


def detect_lan_ipv4() -> str | None:
    candidates: list[str] = []

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            # A conexão UDP apenas consulta a rota local; não envia tráfego.
            probe.connect(("192.0.2.1", 9))
            candidates.append(probe.getsockname()[0])
    except OSError:
        pass

    try:
        hostname = socket.gethostname()
        candidates.extend(
            item[4][0]
            for item in socket.getaddrinfo(hostname, None, socket.AF_INET)
        )
    except OSError:
        pass

    for candidate in dict.fromkeys(candidates):
        if _is_usable_lan_address(candidate):
            return candidate
    return None


def parse_port() -> int:
    raw_port = os.getenv("PORTABLE_PORT", str(DEFAULT_PORT)).strip()
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise ValueError("PORTABLE_PORT precisa ser um número inteiro.") from exc
    if not 1 <= port <= 65535:
        raise ValueError("PORTABLE_PORT precisa estar entre 1 e 65535.")
    return port


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inicia o Praça PDV em modo portátil."
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="confirma uma resposta HTTP e encerra automaticamente",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="não abre o navegador padrão",
    )
    return parser.parse_args()


def _unique_csv_values(*groups: str) -> str:
    values: list[str] = []
    for group in groups:
        for value in group.split(","):
            normalized = value.strip()
            if normalized and normalized not in values:
                values.append(normalized)
    return ",".join(values)


def configure_django_environment(
    portable_root: Path,
    application_root: Path,
    paths: dict[str, Path],
    lan_ip: str | None,
    port: int,
) -> None:
    hosts = ["localhost", "127.0.0.1", "[::1]"]
    origins = [
        f"http://localhost:{port}",
        f"http://127.0.0.1:{port}",
    ]
    if lan_ip:
        hosts.append(lan_ip)
        origins.append(f"http://{lan_ip}:{port}")

    os.environ["DEPLOYMENT_MODE"] = "portable"
    os.environ["PORTABLE_ROOT"] = str(portable_root)
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"
    os.environ["SECRET_KEY"] = ensure_secret_key(paths["config"])
    os.environ["ALLOWED_HOSTS"] = _unique_csv_values(
        ",".join(hosts),
        os.getenv("ALLOWED_HOSTS", ""),
    )
    os.environ["CSRF_TRUSTED_ORIGINS"] = _unique_csv_values(
        ",".join(origins),
        os.getenv("CSRF_TRUSTED_ORIGINS", ""),
    )

    application_root_text = str(application_root)
    if application_root_text not in sys.path:
        sys.path.insert(0, application_root_text)
    os.chdir(application_root)


def create_initial_owner_if_needed(
    logger: logging.Logger,
    *,
    skip: bool = False,
) -> None:
    from django.contrib.auth import get_user_model
    from django.core.management import call_command
    from django.core.management.base import CommandError

    if skip or get_user_model().objects.exists():
        return

    print()
    print("=" * 48)
    print("        PRIMEIRA CONFIGURAÇÃO DO PRAÇA PDV")
    print("=" * 48)
    print("Crie a empresa e o primeiro usuário proprietário.")
    print("A senha será solicitada sem aparecer na tela.")
    print()

    while True:
        company = input("Nome do estabelecimento: ").strip()
        username = input("Usuário do proprietário: ").strip()
        email = input("E-mail do proprietário: ").strip()
        try:
            call_command(
                "create_company_owner",
                company=company,
                username=username,
                email=email,
            )
        except CommandError as exc:
            print()
            print(f"Não foi possível criar o proprietário: {exc}")
            retry = input("Deseja tentar novamente? [S/n]: ").strip().lower()
            if retry in {"n", "nao", "não"}:
                raise RuntimeError(
                    "A configuração inicial não foi concluída."
                ) from exc
            print()
            continue

        logger.info(
            "Configuração inicial concluída; empresa e proprietário criados."
        )
        print()
        print("Configuração inicial concluída com sucesso.")
        return


def prepare_django(
    logger: logging.Logger,
    *,
    skip_owner_setup: bool = False,
) -> object:
    import django
    from django.core.management import call_command

    django.setup()
    logger.info("Aplicando migrations pendentes.")
    call_command("migrate", interactive=False, verbosity=1)
    logger.info("Migrations concluídas.")

    create_initial_owner_if_needed(logger, skip=skip_owner_setup)

    if env_flag("PORTABLE_COLLECTSTATIC", default=True):
        logger.info("Coletando arquivos estáticos.")
        call_command("collectstatic", interactive=False, verbosity=0)
        logger.info("Arquivos estáticos preparados.")

    from config.wsgi import application

    return application


def wait_until_ready(
    port: int,
    server_thread: threading.Thread,
    timeout: int = READY_TIMEOUT_SECONDS,
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and server_thread.is_alive():
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
        try:
            connection.request("GET", "/")
            response = connection.getresponse()
            response.read(1)
            return 200 <= response.status < 400
        except OSError:
            time.sleep(0.2)
        finally:
            connection.close()
    return False


def get_http_status(
    port: int,
    path: str,
    host_header: str | None = None,
) -> int:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    headers = {"Host": host_header} if host_header else {}
    try:
        connection.request("GET", path, headers=headers)
        response = connection.getresponse()
        response.read()
        return response.status
    finally:
        connection.close()


def run_smoke_checks(port: int, lan_ip: str | None) -> None:
    checks = (
        ("/", None, {200, 301, 302, 303, 307, 308}),
        ("/accounts/login/", None, {200}),
        ("/static/css/login.css", None, {200}),
    )
    for path, host_header, expected_statuses in checks:
        status = get_http_status(port, path, host_header)
        if status not in expected_statuses:
            raise RuntimeError(
                f"Smoke test recebeu HTTP {status} em {path}."
            )

    if lan_ip:
        status = get_http_status(port, "/", f"{lan_ip}:{port}")
        if status not in {200, 301, 302, 303, 307, 308}:
            raise RuntimeError(
                f"Acesso pelo host LAN recebeu HTTP {status}."
            )


def show_online_banner(port: int, lan_ip: str | None) -> None:
    local_url = f"http://127.0.0.1:{port}"
    print()
    print("=" * 48)
    print("               PRAÇA PDV LOCAL")
    print("=" * 48)
    print()
    print("Status: ONLINE")
    print()
    print("Neste computador:")
    print(local_url)
    print()
    if lan_ip:
        print("Na rede local:")
        print(f"http://{lan_ip}:{port}")
    else:
        print("Endereço da rede local não pôde ser determinado.")
        print("O acesso neste computador continua disponível.")
    print()
    print("Celulares e tablets devem estar na mesma rede.")
    print("Não remova o dispositivo durante a execução.")
    print("Pressione Ctrl+C para encerrar com segurança.")
    print("=" * 48)
    print(flush=True)


def run_server(
    application: object,
    port: int,
    lan_ip: str | None,
    logger: logging.Logger,
    smoke_test: bool = False,
) -> int:
    from waitress import create_server

    server = create_server(
        application,
        host="0.0.0.0",
        port=port,
        threads=4,
        ident="PracaPDV",
    )
    server_errors: list[BaseException] = []

    def server_target() -> None:
        try:
            server.run()
        except BaseException as exc:  # registrado e propagado pela thread principal
            server_errors.append(exc)
            logger.exception("Falha durante a execução do servidor.")

    server_thread = threading.Thread(
        target=server_target,
        name="praca-pdv-waitress",
        daemon=False,
    )
    server_thread.start()

    if not wait_until_ready(port, server_thread):
        server.close()
        server_thread.join(timeout=5)
        if server_errors:
            raise RuntimeError("O servidor local foi encerrado com erro.") from (
                server_errors[0]
            )
        raise TimeoutError(
            "O servidor não respondeu dentro do tempo esperado."
        )

    local_url = f"http://127.0.0.1:{port}"
    show_online_banner(port, lan_ip)
    logger.info(
        "Servidor online em %s; IP LAN detectado: %s.",
        local_url,
        lan_ip or "indisponível",
    )

    if smoke_test:
        run_smoke_checks(port, lan_ip)
        print("Smoke test HTTP concluído com sucesso.")
        logger.info("Smoke test HTTP concluído com sucesso.")
        server.close()
        server_thread.join(timeout=10)
        return 0

    if env_flag("PORTABLE_OPEN_BROWSER", default=True):
        webbrowser.open(local_url, new=2)

    try:
        while server_thread.is_alive():
            server_thread.join(timeout=1)
    except KeyboardInterrupt:
        print("\nEncerrando o Praça PDV com segurança...")
        logger.info("Encerramento solicitado pelo usuário.")
    finally:
        server.close()
        server_thread.join(timeout=10)

    if server_errors:
        raise RuntimeError("O servidor local foi encerrado com erro.") from (
            server_errors[0]
        )
    logger.info("Servidor encerrado.")
    return 0


def main() -> int:
    arguments = parse_arguments()
    if arguments.no_browser or arguments.smoke_test:
        os.environ["PORTABLE_OPEN_BROWSER"] = "false"

    portable_root = get_portable_root()
    paths = prepare_directories(portable_root)
    logger = configure_logging(paths["logs"])

    try:
        load_environment_file(paths["config"] / "portable.env")
        application_root = get_application_root(portable_root)
        port = parse_port()
        lan_ip = detect_lan_ipv4()
        configure_django_environment(
            portable_root,
            application_root,
            paths,
            lan_ip,
            port,
        )
        logger.info(
            "Inicialização do Praça PDV %s; deployment mode portable; IP LAN: %s.",
            APP_VERSION,
            lan_ip or "indisponível",
        )
        application = prepare_django(
            logger,
            skip_owner_setup=arguments.smoke_test,
        )
        return run_server(
            application,
            port,
            lan_ip,
            logger,
            smoke_test=arguments.smoke_test,
        )
    except KeyboardInterrupt:
        logger.info("Inicialização interrompida pelo usuário.")
        return 0
    except Exception as exc:
        logger.exception("Falha ao iniciar o Praça PDV portátil.")
        print()
        print("ERRO: não foi possível iniciar o Praça PDV.")
        print(str(exc))
        print(f"Consulte o log em: {paths['logs'] / 'portable.log'}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
