from copy import deepcopy
import tempfile
import socket
from threading import Thread
import unittest
from unittest.mock import Mock

from .client import Bridge, Config, instance_lock, send_tcp


PAYLOAD = {"schema_version": 1, "company_name": "BAR PRAÇA KENNEDY", "order_number": 184,
           "ordered_at": "2026-08-27T21:42:00-03:00", "table": "7", "employee_role": "Garçom", "employee_name": "Pedro",
           "items": [{"quantity": "1", "name": "Café", "line_total": "5.00", "observation": "Sem açúcar"}], "total": "5.00", "payment_method": "PIX"}


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Config(server_url="https://example.com", printer_identifier="printer-1", host="127.0.0.1", port=9200, encoding="cp860", codepage=3, state_directory=self.temp.name)
        self.api = Mock()
        self.api.claim.return_value = {"id": 1, "claim_token": "claim", "payload": deepcopy(PAYLOAD), "printer": {"identifier": "printer-1", "characters_per_line": 48, "auto_cut": False}}
        self.sender = Mock()
        self.bridge = Bridge(self.config, self.api, sender=self.sender)

    def test_success_sends_once_and_acknowledges(self):
        self.bridge.step()
        self.sender.assert_called_once()
        self.assertEqual(self.api.acknowledge.call_args.args[0]["status"], "printed")
        self.assertIsNone(self.bridge.journal.read())

    def test_tcp_error_is_reported_without_retry(self):
        self.sender.side_effect = TimeoutError
        self.bridge.step()
        self.sender.assert_called_once()
        self.assertEqual(self.api.acknowledge.call_args.args[0]["status"], "error")

    def test_ack_failure_and_restart_do_not_send_again(self):
        self.api.acknowledge.side_effect = OSError
        with self.assertRaises(OSError):
            self.bridge.step()
        self.assertEqual(self.bridge.journal.read()["status"], "printed")
        restarted = Bridge(self.config, self.api, sender=self.sender)
        self.api.acknowledge.side_effect = None
        restarted.step()
        self.sender.assert_called_once()
        self.api.claim.assert_called_once()

    def test_crash_during_send_reports_uncertain_without_resending(self):
        self.bridge.journal.write({"id": 1, "claim_token": "claim", "status": "sending", "server_url": self.config.server_url, "printer_identifier": self.config.printer_identifier})
        self.bridge.step()
        self.sender.assert_not_called()
        self.api.claim.assert_not_called()
        self.assertEqual(self.api.acknowledge.call_args.args[0]["status"], "error")

    def test_renderer_error_sends_nothing(self):
        self.api.claim.return_value["payload"]["items"][0]["name"] = "🍺"
        self.bridge.step()
        self.sender.assert_not_called()
        self.assertEqual(self.api.acknowledge.call_args.args[0]["status"], "error")

    def test_wrong_printer_sends_nothing(self):
        self.api.claim.return_value["printer"]["identifier"] = "other"
        self.bridge.step()
        self.sender.assert_not_called()
        self.assertEqual(self.api.acknowledge.call_args.args[0]["status"], "error")

    def test_only_one_process_per_state_directory(self):
        with instance_lock(self.temp.name):
            with self.assertRaises(RuntimeError), instance_lock(self.temp.name):
                pass

    def test_remote_http_is_rejected(self):
        with self.assertRaises(ValueError):
            Config(server_url="http://example.com", printer_identifier="id", host="host", port=9100, encoding="cp860", codepage=3, state_directory=self.temp.name)

    def test_tcp_transport_uses_configured_port_and_exact_bytes(self):
        from dataclasses import replace
        received = []
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            listener.settimeout(5)
            config = replace(self.config, port=listener.getsockname()[1])
            def receive():
                with listener.accept()[0] as conn:
                    conn.settimeout(5)
                    while True:
                        chunk = conn.recv(1024)
                        if not chunk:
                            break
                        received.append(chunk)
            thread = Thread(target=receive)
            thread.start()
            expected = b"\x1b@" + "PRAÇA ç ã é".encode("cp860") + b"\n"
            send_tcp(config, expected)
            thread.join(timeout=10)
            self.assertFalse(thread.is_alive())
            self.assertEqual(b"".join(received), expected)
