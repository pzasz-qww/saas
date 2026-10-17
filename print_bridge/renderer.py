"""One layout shared by text/HTML previews and ESC/POS output.

Command reference: https://download4.epson.biz/sec_pubs/pos/reference_en/escpos/commands.html
The encoding and ESC t table number are independent, explicit hardware settings.
"""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from html import escape
import textwrap
import unicodedata


ESC = b"\x1b"
GS = b"\x1d"


@dataclass(frozen=True)
class Line:
    text: str
    bold: bool = False
    width: int = 1
    height: int = 1
    centered: bool = False


def clean_text(value):
    # User content must never inject printer commands or bidi/control characters.
    value = unicodedata.normalize("NFC", str(value))
    value = "".join(" " if unicodedata.category(c).startswith("C") else c for c in value)
    return " ".join(value.split())


def money(value):
    value = Decimal(str(value))
    if not value.is_finite() or value < 0:
        raise ValueError("Valor monetário inválido.")
    return "R$ " + f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def quantity(value):
    value = Decimal(str(value))
    if not value.is_finite() or value <= 0:
        raise ValueError("Quantidade inválida.")
    return format(value.normalize(), "f").replace(".", ",")


def wrapped(value, columns):
    return textwrap.wrap(clean_text(value), width=columns, break_long_words=True, break_on_hyphens=False) or [""]


def pair(left, right, columns):
    right = clean_text(right)
    if len(right) >= columns - 2:
        raise ValueError("Valor não cabe na largura configurada.")
    available = columns - len(right) - 1
    parts = wrapped(left, available)
    return [parts[0].ljust(columns - len(right)) + right, *parts[1:]]


def layout(payload, columns=48):
    if payload.get("schema_version") != 1:
        raise ValueError("Versão de snapshot não suportada.")
    if not isinstance(columns, int) or not 32 <= columns <= 64:
        raise ValueError("Configure de 32 a 64 caracteres por linha.")
    original_time = datetime.fromisoformat(payload["ordered_at"])
    if original_time.utcoffset() is None:
        raise ValueError("O horário original precisa incluir o fuso horário.")
    lines = [Line(text, bold=True, width=2, height=2, centered=True)
             for text in wrapped(payload["company_name"].upper(), columns // 2)]
    lines += [Line(text, bold=True, centered=True) for text in wrapped(f"PEDIDO #{payload['order_number']}", columns)]
    lines += [Line(""), Line(pair(original_time.strftime("%d/%m/%Y"), original_time.strftime("%H:%M"), columns)[0])]
    if payload.get("table"):
        lines += [Line(t) for t in wrapped(f"Mesa {payload['table']}", columns)]
    lines += [Line(""), *[Line(t) for t in wrapped(f"{payload['employee_role']}: {payload['employee_name']}", columns)], Line(""), Line("-" * columns)]
    def observation(value):
        return [Line("   >> " + text + " <<", bold=True, height=2) for text in wrapped(clean_text(value).upper(), columns - 9)]
    for item in payload["items"]:
        lines += [Line(t, bold=True) for t in pair(f"{quantity(item['quantity'])}x {clean_text(item['name']).upper()}", money(item["line_total"]), columns)]
        if item.get("observation"):
            lines += observation(item["observation"])
        lines.append(Line(""))
    if payload.get("observation"):
        lines += observation(payload["observation"])
    lines += [Line("-" * columns), *[Line(t, bold=True, height=2) for t in pair("TOTAL", money(payload["total"]), columns)], Line("")]
    lines += [Line(t, bold=True) for t in wrapped(f"Pagamento: {payload['payment_method']}", columns)]
    return lines


def render_text(payload, columns=48):
    return "\n".join(line.text.center(columns).rstrip() if line.centered else line.text for line in layout(payload, columns)) + "\n"


def render_html(payload, columns=48):
    rows = []
    for line in layout(payload, columns):
        style = f"font-weight:{700 if line.bold else 400};text-align:{'center' if line.centered else 'left'};"
        if line.height == 2:
            style += "font-size:2em;"
        # Preserve the column grid; hardware width/height is represented separately.
        if line.width == 1 and line.height == 2:
            style += "font-size:1em;line-height:2;"
        text = escape(line.text) or "&nbsp;"
        if line.width == 1 and line.height == 2:
            text = '<span style="display:inline-block;transform:scaleY(1.7);">' + text + '</span>'
        rows.append(f'<div style="{style}">{text}</div>')
    return f'<div class="ticket" style="font-family:monospace;white-space:pre;width:{columns}ch;">' + "".join(rows) + "</div>"


def render_escpos(payload, *, columns=48, encoding, codepage, auto_cut=False, cut_mode="partial", feed_lines=4):
    if not isinstance(codepage, int) or not 0 <= codepage <= 255:
        raise ValueError("Informe o número ESC t documentado pela impressora (0–255).")
    if cut_mode not in {"full", "partial"} or not 0 <= feed_lines <= 10:
        raise ValueError("Corte ou avanço de papel inválido.")
    output = bytearray(ESC + b"@" + ESC + b"M\x00" + ESC + b"t" + bytes([codepage]))
    for line in layout(payload, columns):
        encoded = line.text.encode(encoding, errors="strict")
        # This layout targets single-byte ESC/POS codepages, never guessed UTF-8.
        if len(encoded) != len(line.text) or any(b < 32 or b == 127 for b in encoded):
            raise ValueError("Use um charset de byte único compatível com a tabela da impressora.")
        output += ESC + b"a" + bytes([1 if line.centered else 0])
        output += ESC + b"E" + bytes([int(line.bold)])
        output += GS + b"!" + bytes([((line.width - 1) << 4) | (line.height - 1)])
        output += encoded + b"\n"
    output += ESC + b"a\x00" + ESC + b"E\x00" + GS + b"!\x00"
    output += ESC + b"d" + bytes([feed_lines])
    if auto_cut:
        output += GS + b"V" + bytes([1 if cut_mode == "partial" else 0])
    return bytes(output)
