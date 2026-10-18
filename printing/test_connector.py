import json
from datetime import timedelta
from django.test import Client
from django.utils import timezone
from orders.tests.helpers import make_company, make_user
from .models import ConnectorLink, Printer, PrintSettings
from .queue import authenticate
from .test_helpers import PrintingCase


class ConnectorTests(PrintingCase):
    def setUp(self):
        super().setUp()
        self.owner=make_user(company=self.company)
        self.client.force_login(self.owner)

    def link(self):
        response=self.client.post('/printing/connector/download/')
        self.assertEqual(response.status_code,200)
        return json.loads(response.content)['link']

    def exchange(self,secret):
        return self.client.post('/printing/api/v1/connector/exchange/',json.dumps({'link':secret}),content_type='application/json')

    def test_single_use_and_expiry(self):
        secret=self.link()
        response=self.exchange(secret)
        self.assertEqual(response.status_code,200)
        credential=authenticate(response.json()['token'])
        self.assertEqual(credential.company_id,self.company.pk)
        self.assertEqual(self.exchange(secret).status_code,410)
        secret=self.link()
        ConnectorLink.objects.filter(used_at__isnull=True).update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.exchange(secret).status_code,410)

    def test_permissions_and_csrf(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.post('/printing/connector/download/').status_code,403)
        strict=Client(enforce_csrf_checks=True);strict.force_login(self.owner)
        self.assertEqual(strict.post('/printing/connector/download/').status_code,403)

    def test_configuration_is_scoped_and_does_not_enable_on_exchange(self):
        original=self.settings.default_printer_id
        response=self.exchange(self.link()).json()
        self.settings.refresh_from_db()
        self.assertEqual(self.settings.default_printer_id,original)
        other=make_company();foreign=PrintSettings.objects.create(company=other,automatic=False)
        payload={'name':'POS-80','columns':48,'cut':True,'automatic':True}
        result=self.client.post('/printing/api/v1/connector/configure/',json.dumps(payload),content_type='application/json',HTTP_AUTHORIZATION='Bearer '+response['token'])
        self.assertEqual(result.status_code,200)
        self.settings.refresh_from_db();foreign.refresh_from_db()
        self.assertTrue(self.settings.automatic)
        self.assertTrue(self.settings.default_printer.auto_cut)
        self.assertEqual(str(self.settings.default_printer.identifier),response['printer_identifier'])
        self.assertFalse(foreign.automatic)
        payload['columns']=1
        self.assertEqual(self.client.post('/printing/api/v1/connector/configure/',json.dumps(payload),content_type='application/json',HTTP_AUTHORIZATION='Bearer '+response['token']).status_code,400)

    def test_inactive_company_and_invalid_token(self):
        secret=self.link();self.company.active=False;self.company.save()
        self.assertEqual(self.exchange(secret).status_code,410)
        self.assertEqual(self.client.post('/printing/api/v1/connector/status/').status_code,401)
        self.assertEqual(self.client.post('/printing/api/v1/connector/exchange/','[]',content_type='application/json').status_code,400)
