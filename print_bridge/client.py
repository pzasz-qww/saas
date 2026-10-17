"""Standard-library-only bridge, suitable for Windows 11 and Linux."""
import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import socket
import time
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .renderer import render_escpos, render_text


log = logging.getLogger("print_bridge")


@dataclass(frozen=True)
class Config:
    server_url: str
    printer_identifier: str
    host: str
    port: int
    encoding: str
    codepage: int
    state_directory: str
    token_env: str = "PRINT_BRIDGE_TOKEN"
    poll_seconds: float = 2.0
    timeout_seconds: float = 10.0
    feed_lines: int = 4
    cut_mode: str = "partial"
    transport: str = "tcp"
    printer_name: str = ""

    def __post_init__(self):
        parsed = urlsplit(self.server_url)
        if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}):
            raise ValueError("Use HTTPS; HTTP é permitido somente no computador local.")
        if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("URL do SaaS inválida.")
        if self.transport not in {"tcp", "windows_raw"}:
            raise ValueError("Transporte inválido: use tcp ou windows_raw.")
        if self.transport == "windows_raw" and not self.printer_name.strip():
            raise ValueError("Informe o nome exato da fila de impressão do Windows.")
        if self.transport == "tcp" and (not self.host or not 1 <= self.port <= 65535):
            raise ValueError("IP/host e porta da impressora são obrigatórios.")
        if not 0 <= self.codepage <= 255 or not self.encoding:
            raise ValueError("Defina charset e codepage conforme o manual da impressora.")
        if not 0.5 <= self.poll_seconds <= 300 or not 1 <= self.timeout_seconds <= 120:
            raise ValueError("Intervalo de consulta ou timeout inválido.")
        if self.cut_mode not in {"full", "partial"} or not 0 <= self.feed_lines <= 10:
            raise ValueError("Corte ou avanço de papel inválido.")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Redirecionamento recusado; confira a URL do SaaS.")


class APIClient:
    def __init__(self, config, token):
        self.config = config
        self.token = token
        self.opener = build_opener(NoRedirect)

    def post(self, route, data):
        request = Request(self.config.server_url.rstrip("/") + "/printing/api/v1/" + route,
                          data=json.dumps(data).encode("utf-8"), method="POST",
                          headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"})
        with self.opener.open(request, timeout=self.config.timeout_seconds) as response:
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ValueError("Resposta maior que o limite.")
            return json.loads(raw)

    def claim(self):
        return self.post("jobs/claim/", {}).get("job")

    def acknowledge(self, entry):
        result = self.post(f"jobs/{int(entry['id'])}/result/", {
            "claim_token": entry["claim_token"], "status": entry["status"], "error": entry.get("error", ""),
        })
        if result.get("status") != entry["status"]:
            raise ValueError("Confirmação inesperada do SaaS.")


def send_tcp(config, data):
    with socket.create_connection((config.host, config.port), timeout=config.timeout_seconds) as connection:
        connection.settimeout(config.timeout_seconds)
        connection.sendall(data)


def send_print(config, data):
    if config.transport == "windows_raw":
        from .windows_raw import send_windows_raw
        return send_windows_raw(config, data)
    return send_tcp(config, data)


class Journal:
    """Durable acknowledgement outbox; never automatically repeats TCP writes."""
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "pending.json"

    def read(self):
        return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else None

    def write(self, entry):
        temporary = self.directory / "pending.tmp"
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(entry, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)

    def clear(self):
        self.path.unlink(missing_ok=True)


@contextmanager
def instance_lock(directory):
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    with (path / "bridge.lock").open("a+b") as stream:
        try:
            if os.fstat(stream.fileno()).st_size == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("Já existe um bridge usando esta pasta de estado.") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


class Bridge:
    def __init__(self, config, api, *, sender=send_print):
        self.config, self.api, self.sender = config, api, sender
        self.journal = Journal(config.state_directory)

    def acknowledge_pending(self):
        entry = self.journal.read()
        if not entry:
            return False
        if entry.get("server_url") != self.config.server_url or entry.get("printer_identifier") != self.config.printer_identifier:
            raise ValueError("A pasta de estado pertence a outro SaaS/impressora; mantenha a configuração original para confirmar o trabalho.")
        if entry["status"] == "sending":
            entry.update(status="error", error="Bridge interrompido durante envio. Resultado físico incerto; confira o papel antes de reimprimir.")
            self.journal.write(entry)
        self.api.acknowledge(entry)
        self.journal.clear()
        return True

    def step(self):
        if self.acknowledge_pending():
            return True
        job = self.api.claim()
        if job is None:
            return False
        entry = {"id": job["id"], "claim_token": job["claim_token"], "status": "sending",
                 "server_url": self.config.server_url, "printer_identifier": self.config.printer_identifier}
        self.journal.write(entry)  # Persist before a single byte can reach the printer.
        try:
            if job["printer"]["identifier"] != self.config.printer_identifier:
                raise ValueError("Identificador da impressora diferente da configuração local.")
            data = render_escpos(job["payload"], columns=job["printer"]["characters_per_line"],
                encoding=self.config.encoding, codepage=self.config.codepage,
                auto_cut=job["printer"]["auto_cut"], cut_mode=self.config.cut_mode, feed_lines=self.config.feed_lines)
            self.sender(self.config, data)
        except Exception as exc:
            # Do not include credentials, payload text or potentially sensitive exception strings.
            entry.update(status="error", error=f"Falha de renderização/envio {self.config.transport} ({type(exc).__name__}). Resultado físico pode ser parcial; confira a impressora.")
        else:
            entry["status"] = "printed"
        self.journal.write(entry)
        self.acknowledge_pending()
        return True


def main():
    parser = argparse.ArgumentParser(description="Bridge local de impressão ESC/POS")
    parser.add_argument("--config", required=True)
    parser.add_argument("--once", action="store_true", help="Processa no máximo um trabalho ou confirmação pendente")
    parser.add_argument("--preview", help="Mostra um snapshot JSON local sem consultar fila ou impressora")
    parser.add_argument("--test-ticket", help="Envia explicitamente um snapshot JSON local à impressora")
    parser.add_argument("--columns", type=int, default=48, help="Largura do teste/preview local em caracteres")
    parser.add_argument("--cut", action="store_true", help="Habilita corte somente no teste físico explícito")
    args = parser.parse_args()
    config = Config(**json.loads(Path(args.config).read_text(encoding="utf-8")))
    if args.preview or args.test_ticket:
        payload = json.loads(Path(args.preview or args.test_ticket).read_text(encoding="utf-8"))
        if args.preview:
            print(render_text(payload, args.columns))
        else:
            result = send_print(config, render_escpos(payload, columns=args.columns, encoding=config.encoding, codepage=config.codepage, feed_lines=config.feed_lines, cut_mode=config.cut_mode, auto_cut=args.cut))
            print(f"Envio aceito pelo transporte {config.transport}." + (f" Trabalho Windows: {result}." if result is not None else "") + " Confira a saída física.")
        return
    token = os.environ.get(config.token_env)
    if not token:
        parser.error(f"Defina a variável {config.token_env} com a credencial do bridge.")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    bridge = Bridge(config, APIClient(config, token))
    with instance_lock(config.state_directory):
        while True:
            try:
                bridge.step()
            except KeyboardInterrupt:
                return
            except Exception as exc:
                log.error("Bridge sem confirmação (%s). Estado preservado; não haverá reenvio TCP automático.", type(exc).__name__)
                if args.once:
                    raise SystemExit(1) from None
            if args.once:
                return
            time.sleep(config.poll_seconds)
