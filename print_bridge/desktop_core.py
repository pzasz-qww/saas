"""Windows connector storage and transport; no Django dependency."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess

from .client import Config, APIClient


def data_dir():
    return Path(os.environ['LOCALAPPDATA']) / 'PracaPDV' / 'Connector'


class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def protect(data, decrypt=False):
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    buf = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                   ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel.LocalFree(output.data)


def save_settings(path, value):
    """Encrypt the entire configuration for this Windows user, atomically."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_bytes(protect(json.dumps(value).encode('utf-8')))
    temporary.replace(path)


def load_settings(path):
    return json.loads(protect(Path(path).read_bytes(), decrypt=True))


def connection_file(path):
    path = Path(path)
    if path.stat().st_size > 4096:
        raise ValueError('Arquivo de conexão inválido.')
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if data.get('version') != 1 or not isinstance(data.get('link'), str) or not 32 <= len(data['link']) <= 128:
        raise ValueError('Arquivo de conexão inválido.')
    # Reuse HTTPS / loopback-only validation before any credential is sent.
    make_config(data['server_url'], 'setup', Path('.'))
    return data


def make_config(url, identifier, state, **kwargs):
    return Config(server_url=url, printer_identifier=identifier, host=kwargs.get('host', ''),
        port=int(kwargs.get('port', 0)), encoding=kwargs.get('encoding', 'cp860'),
        codepage=int(kwargs.get('codepage', 3)), state_directory=str(state),
        transport=kwargs.get('transport', 'windows_raw'), printer_name=kwargs.get('printer_name', 'POS-80'),
        feed_lines=5, cut_mode='partial')


def printers():
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
        '[Console]::OutputEncoding=[Text.UTF8Encoding]::new(); ConvertTo-Json -InputObject @(Get-Printer | Select-Object -ExpandProperty Name) -Compress'],
        capture_output=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError('Não foi possível listar as impressoras. Confira o serviço de impressão do Windows.')
    return json.loads(result.stdout.decode('utf-8-sig'))


def test_payload():
    from datetime import datetime
    return {'schema_version': 1, 'company_name': 'TESTE DE IMPRESSÃO', 'order_number': 'TESTE',
        'ordered_at': datetime.now().astimezone().isoformat(), 'table': 'Configuração',
        'employee_role': 'Operador', 'employee_name': 'Teste', 'items': [
            {'quantity': '1.00', 'name': 'Café e pão', 'unit_price': '0.01',
             'line_total': '0.01', 'observation': 'ação, coração, açúcar'}],
        'observation': 'SEM VALOR COMERCIAL. Confira texto e corte.', 'total': '0.01', 'payment_method': 'TESTE'}
