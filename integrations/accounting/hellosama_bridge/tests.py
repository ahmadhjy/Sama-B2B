import hashlib
import hmac
import json
import os
import time
import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from accounts_core.models import Client, Currency, Employee, Supplier
from catalog.models import ServiceType
from portal.accounts import sync_portal_account
from sales.models import SalesInvoice,SalesInvoiceLine
from treasury.models import MoneyAccount,Payment

@override_settings(ALLOWED_HOSTS=['testserver'],PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class BridgeTests(TestCase):
    def setUp(self):
        self.key='test-bridge-secret-with-at-least-32-characters'
        env=patch.dict(os.environ,{'HELLOSAMA_SHARED_SECRET':self.key});env.start();self.addCleanup(env.stop)
        Currency.objects.get_or_create(code='USD',defaults={'name':'US Dollar','is_active':True})
        self.company=Client.objects.create(client_code='BRIDGE1',name_en='Bridge company')
        self.other=Client.objects.create(client_code='BRIDGE2',name_en='Other company')
        for company in [self.company,self.other]: self.assertEqual(sync_portal_account(company,enabled=True,password='PortalPass!234'),[])
        employee=Employee.objects.create(name='Sales test',role='SALES')
        self.invoice=SalesInvoice.objects.create(invoice_no='BRIDGE-INV1',client=self.company,sales_employee=employee,issue_date=date.today(),currency='USD',status=SalesInvoice.Status.POSTED,grand_total=Decimal('200'),grand_total_usd=Decimal('200'))
        self.other_invoice=SalesInvoice.objects.create(invoice_no='BRIDGE-INV2',client=self.other,sales_employee=employee,issue_date=date.today(),currency='USD',status=SalesInvoice.Status.POSTED,grand_total=Decimal('500'),grand_total_usd=Decimal('500'))
        supplier=Supplier.objects.create(supplier_code='BRIDGE-SUP',name='PRIVATE-SUPPLIER')
        service=ServiceType.objects.create(name='Ticket',code='BRIDGE')
        SalesInvoiceLine.objects.create(invoice=self.invoice,supplier=supplier,service_type=service,line_employee=employee,qty=1,sell_price=200,cost_price=121,line_data={'private_note':'DO-NOT-EXPOSE'})

    def headers(self,path,body,nonce=None,stamp=None):
        nonce=nonce or uuid.uuid4().hex;stamp=stamp or str(int(time.time()))
        canonical='\n'.join(['POST',path,stamp,nonce,hashlib.sha256(body).hexdigest()])
        signature=hmac.new(self.key.encode(),canonical.encode(),hashlib.sha256).hexdigest()
        return {'HTTP_X_HELLOSAMA_TIME':stamp,'HTTP_X_HELLOSAMA_NONCE':nonce,'HTTP_X_HELLOSAMA_SIGNATURE':signature}

    def call(self,action,data,**kwargs):
        path=f'/hellosama-api/{action}/';body=json.dumps(data,separators=(',',':'),sort_keys=True).encode()
        return self.client.post(path,body,content_type='application/json',**self.headers(path,body,**kwargs))

    def test_unsigned_and_tampered_calls_rejected(self):
        self.assertEqual(self.client.post('/hellosama-api/companies/',b'{}',content_type='application/json').status_code,401)
        headers=self.headers('/hellosama-api/companies/',b'{}')
        self.assertEqual(self.client.post('/hellosama-api/companies/',b'{"tampered":true}',content_type='application/json',**headers).status_code,401)

    def test_replayed_and_old_requests_rejected(self):
        nonce=uuid.uuid4().hex
        self.assertEqual(self.call('companies',{},nonce=nonce).status_code,200)
        self.assertEqual(self.call('companies',{},nonce=nonce).status_code,401)
        self.assertEqual(self.call('companies',{},stamp=str(int(time.time())-180)).status_code,401)

    def test_company_authentication_and_password_version(self):
        data={'account_number':'bridge1','password':'PortalPass!234'}
        response=self.call('authenticate',data);self.assertEqual(response.status_code,200)
        result=response.json();self.assertEqual(result['id'],str(self.company.pk));self.assertNotIn('password',result)
        old=result['version'];sync_portal_account(self.company,enabled=True,password='ChangedPass!987')
        self.assertEqual(self.call('authenticate',data).status_code,401)
        self.assertNotEqual(self.call('status',{'company_id':str(self.company.pk)}).json()['version'],old)

    def test_disabled_account_cannot_read_financials(self):
        sync_portal_account(self.company,enabled=False)
        self.assertEqual(self.call('finance',{'company_id':str(self.company.pk),'kind':'statement'}).status_code,404)
        self.assertFalse(self.call('status',{'company_id':str(self.company.pk)}).json()['active'])

    def test_invoice_scope_and_no_internal_costs(self):
        result=self.call('finance',{'company_id':str(self.company.pk),'kind':'invoice','id':str(self.invoice.pk)})
        self.assertEqual(result.status_code,200)
        for forbidden in [b'PRIVATE-SUPPLIER',b'DO-NOT-EXPOSE',b'cost_price']:
            self.assertNotIn(forbidden,result.content)
        result=self.call('finance',{'company_id':str(self.company.pk),'kind':'invoice','id':str(self.other_invoice.pk)})
        self.assertEqual(result.status_code,404)

    def test_only_client_invoices_are_listed(self):
        result=self.call('finance',{'company_id':str(self.company.pk),'kind':'invoices'}).json()
        self.assertEqual([str(row['id']) for row in result['invoices']],[str(self.invoice.pk)])

    def test_receipt_scope_and_internal_notes(self):
        account=MoneyAccount.objects.create(name='PRIVATE-BANK',type=MoneyAccount.AccountType.CASH,currency='USD')
        payment=Payment.objects.create(receipt_no='BRIDGE-PAY1',direction=Payment.Direction.IN,party_type=Payment.PartyType.CLIENT,client=self.company,money_account=account,date=date.today(),currency='USD',amount=50,status=Payment.Status.POSTED,note='PRIVATE-NOTE')
        result=self.call('finance',{'company_id':str(self.company.pk),'kind':'receipt','id':str(payment.pk)})
        self.assertEqual(result.status_code,200);self.assertNotIn(b'PRIVATE-NOTE',result.content);self.assertNotIn(b'PRIVATE-BANK',result.content)
        self.assertEqual(self.call('finance',{'company_id':str(self.other.pk),'kind':'receipt','id':str(payment.pk)}).status_code,404)

    def test_no_financial_write_actions(self):
        self.assertEqual(self.call('delete',{'company_id':str(self.company.pk)}).status_code,404)
        self.assertTrue(Client.objects.filter(pk=self.company.pk).exists())
