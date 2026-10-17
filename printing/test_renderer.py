from copy import deepcopy
from django.test import SimpleTestCase
from print_bridge.renderer import layout, render_escpos, render_html, render_text


SAMPLE = {
    "schema_version": 1, "company_name": "BAR PRAÇA KENNEDY", "order_number": 184,
    "ordered_at": "2026-08-27T21:42:00-03:00", "table": "7",
    "employee_role": "Garçom", "employee_name": "Pedro",
    "items": [{"quantity": "2", "name": "Heineken", "observation": "", "line_total": "20.00"},
              {"quantity": "1", "name": "Calabresa", "observation": "sem cebola", "line_total": "45.00"}],
    "observation": "", "total": "65.00", "payment_method": "PIX",
}


class RendererTests(SimpleTestCase):
    def test_official_ticket_content(self):
        output = render_text(SAMPLE)
        for fragment in ["BAR PRAÇA KENNEDY", "PEDIDO #184", "27/08/2026", "21:42", "Mesa 7", "Garçom: Pedro", "2x HEINEKEN", "R$ 20,00", ">> SEM CEBOLA <<", "TOTAL", "R$ 65,00", "Pagamento: PIX"]:
            self.assertIn(fragment, output)
        self.assertNotIn("R$ 10,00", output)

    def test_escpos_visual_emphasis_and_optional_cut(self):
        output = render_escpos(SAMPLE, encoding="cp860", codepage=3, auto_cut=True)
        self.assertIn(b"\x1ba\x01\x1bE\x01\x1d!\x11" + "BAR PRAÇA KENNEDY".encode("cp860"), output)
        self.assertIn(b"\x1bE\x01\x1d!\x01   >> SEM CEBOLA <<", output)
        self.assertIn(b"\x1bE\x01\x1d!\x01TOTAL", output)
        self.assertIn(b"\x1bE\x01\x1d!\x002x HEINEKEN", output)
        self.assertTrue(output.endswith(b"\x1bd\x04\x1dV\x01"))
        self.assertNotIn(b"\x1dV", render_escpos(SAMPLE, encoding="cp860", codepage=3))

    def test_widths_long_text_and_money_alignment(self):
        sample = deepcopy(SAMPLE)
        sample["items"][0]["name"] = "Produto com um nome muito longo " * 4
        sample["items"][1]["observation"] = "Observação longa " * 12
        for width in [32, 42, 48, 64]:
            for line in layout(sample, width):
                self.assertLessEqual(len(line.text) * line.width, width)
            self.assertTrue(next(line for line in render_text(sample, width).splitlines() if "R$ 20,00" in line).endswith("R$ 20,00"))

    def test_unrepresentable_encoding_fails_before_send(self):
        with self.assertRaises(UnicodeEncodeError):
            render_escpos(SAMPLE, encoding="ascii", codepage=0)
        with self.assertRaises(ValueError):
            render_escpos(SAMPLE, encoding="utf-8", codepage=0)

    def test_html_escapes_and_escpos_strips_control_characters(self):
        sample = deepcopy(SAMPLE)
        sample["employee_name"] = "<script>alert(1)</script>\x1b\x00"
        html = render_html(sample)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("\x1b", render_text(sample))

    def test_preview_does_not_mutate_payload(self):
        sample = deepcopy(SAMPLE)
        render_text(sample)
        render_html(sample)
        render_escpos(sample, encoding="cp860", codepage=3)
        self.assertEqual(sample, SAMPLE)
