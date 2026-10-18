import os
import json
import tempfile
import unittest
from pathlib import Path
from .desktop_core import connection_file, protect, save_settings, load_settings, test_payload
from .renderer import render_escpos


class DesktopTests(unittest.TestCase):
    def test_connection_file_rejects_remote_http_and_credentials_in_url(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'link.pdvconnect'
            for url in ['http://example.com','https://user:secret@example.com']:
                path.write_text(json.dumps({'version':1,'link':'a'*43,'server_url':url}),encoding='utf-8')
                with self.assertRaises(ValueError): connection_file(path)
            path.write_text(json.dumps({'version':1,'link':'a'*43,'server_url':'https://example.com'}),encoding='utf-8')
            self.assertEqual(connection_file(path)['server_url'],'https://example.com')

    @unittest.skipUnless(os.name=='nt','Windows DPAPI')
    def test_encrypted_storage_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'settings.bin'
            save_settings(path,{'token':'secret-never-plaintext','company':'Praça'})
            self.assertNotIn(b'secret-never-plaintext',path.read_bytes())
            self.assertEqual(load_settings(path)['company'],'Praça')

    def test_test_ticket_contains_cut(self):
        data=render_escpos(test_payload(),columns=48,encoding='cp860',codepage=3,auto_cut=True,cut_mode='partial')
        self.assertIn(b'\x1dV',data)
