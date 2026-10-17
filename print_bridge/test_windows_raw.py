from dataclasses import replace
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch, call

from .client import Config, send_print
from .windows_raw import send_windows_raw


class WindowsRawTests(TestCase):
    def setUp(self):
        self.config = SimpleNamespace(printer_name="POS-80")
        self.spooler = Mock()
        self.spooler.open.return_value = 42
        self.spooler.start.return_value = 7

    def test_partial_writes_preserve_exact_bytes_and_close(self):
        data = b"\x1b@abc\x00\n"
        self.spooler.write.side_effect = [3, len(data) - 3]
        self.assertEqual(send_windows_raw(self.config, data, spooler=self.spooler), 7)
        self.assertEqual(self.spooler.write.call_args_list, [call(42, data), call(42, data[3:])])
        self.assertEqual(self.spooler.checked.call_args_list, [call("StartPagePrinter", 42), call("EndPagePrinter", 42), call("EndDocPrinter", 42), call("ClosePrinter", 42)])

    def test_failed_write_aborts_only_current_document_and_closes(self):
        self.spooler.write.side_effect = OSError("write failed")
        with self.assertRaises(OSError):
            send_windows_raw(self.config, b"abc", spooler=self.spooler)
        self.spooler.checked.assert_any_call("AbortPrinter", 42)
        self.assertEqual(self.spooler.checked.call_args_list[-1], call("ClosePrinter", 42))
        self.assertNotIn(call("EndDocPrinter", 42), self.spooler.checked.call_args_list)

    def test_zero_write_stops_instead_of_looping(self):
        self.spooler.write.return_value = 0
        with self.assertRaises(OSError):
            send_windows_raw(self.config, b"abc", spooler=self.spooler)
        self.spooler.write.assert_called_once()

    def test_start_failure_closes_without_aborting_unstarted_document(self):
        self.spooler.start.side_effect = OSError("start failed")
        with self.assertRaises(OSError):
            send_windows_raw(self.config, b"abc", spooler=self.spooler)
        self.spooler.checked.assert_called_once_with("ClosePrinter", 42)

    def test_windows_transport_needs_queue_name_not_network_address(self):
        config = Config(server_url="http://localhost:8000", printer_identifier="test", host="", port=0, encoding="cp860", codepage=3, state_directory="state", transport="windows_raw", printer_name="POS-80")
        with patch("print_bridge.windows_raw.send_windows_raw", return_value=7) as send:
            self.assertEqual(send_print(config, b"abc"), 7)
            send.assert_called_once_with(config, b"abc")
        with self.assertRaises(ValueError):
            replace(config, printer_name="")
        with self.assertRaises(ValueError):
            replace(config, transport="unknown")
