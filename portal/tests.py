import json
import tempfile
from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch, Mock
from django.conf import settings
from django.core import mail
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase, override_settings, Client
from django.urls import reverse
from django.utils import timezone
from portal import workflow
from portal.accounting import provision, AccountingUnavailable
from portal.ai import reserve, settle, generate, AssistantUnavailable
from portal.files import save_attachment
from portal.forms import RequestForm
from portal.mailbox import ingest_message
from portal.models import (User,Company,Draft,TravelRequest,Quote,Approval,Message,Attachment,Audit,Notification,
    Delivery,AIBudget,MailReview,PushSubscription)
from portal.notifications import process_deliveries, safe_push_endpoint
from portal.permissions import visible_requests,can_work,can_attachment

@override_settings(DEBUG=True,ACCOUNTING_ENABLED=False,AI_ENABLED=False,EMAIL_ENABLED=False,IMAP_ENABLED=False,
    VAPID_PRIVATE_KEY='',VAPID_PUBLIC_KEY='',PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    ALLOWED_HOSTS=['testserver'],NOTIFICATION_TEST_MODE=False,SMS_ENABLED=False)
class PortalTests(TestCase):
    def setUp(self):
        self.storage=tempfile.TemporaryDirectory()
        self.override=override_settings(MEDIA_ROOT=self.storage.name);self.override.enable()
        self.addCleanup(self.override.disable);self.addCleanup(self.storage.cleanup)
        self.company=Company.objects.create(name='Cedar test',account_number='C001')
        self.other=Company.objects.create(name='Other test',account_number='C002')
        self.owner=self.user('owner','owner',self.company,True)
        self.requester=self.user('requester','requester',self.company)
        self.approver=self.user('approver','accountant',self.company,True)
        self.accountant=self.user('accountant','accountant',self.company)
        self.outsider=self.user('outsider','owner',self.other,True)
        self.ceo=self.user('ceo','ceo')
        self.sales=self.user('sales','sales')
        self.sales2=self.user('sales2','sales')
        self.finance=self.user('finance','finance')
        self.req=self.request()

    def user(self,name,role,company=None,approve=False):
        member = User.objects.create_user(username=name,password='TestPass!234',first_name=name.title(),last_name='Tester',
            email=name+'@example.com',phone='+96170123456',passport_number='PA1234567',
            passport_expiry=timezone.localdate()+timedelta(days=365),nationality='Lebanese',role=role,company=company,can_approve=approve)
        if company:
            save_attachment(SimpleUploadedFile('profile-passport.pdf', b'%PDF-1.4 FICTIONAL TEST ONLY'), member, passport_owner=member)
        return member

    def request(self,**kwargs):
        values={'reference':'HS-26-ABCDEF12','company':self.company,'requester':self.requester,'title':'Bangkok trip',
            'origin':'Beirut','destination':'Bangkok','departure':timezone.localdate()+timedelta(days=20),
            'return_date':timezone.localdate()+timedelta(days=25),'travellers':2}
        values.update(kwargs)
        return TravelRequest.objects.create(**values)

    def signin(self,user):
        self.client.force_login(user,backend='portal.auth.LocalBackend')

    def quote(self):
        if not self.req.assignee_id:
            workflow.claim_request(self.sales,self.req.pk);self.req.refresh_from_db()
        return workflow.issue_quote(self.sales,self.req.pk,{'amount':Decimal('1500.00'),'currency':'USD','details':'Flights and hotel',
            'inclusions':'Breakfast','exclusions':'Personal expenses','payment_terms':'Pay after confirmation',
            'valid_until':timezone.now()+timedelta(days=2)})

    def awaiting(self):
        quote=self.quote();workflow.request_approval(self.requester,self.req.pk,quote.pk);quote.refresh_from_db();return quote

    def test_all_dashboard_pages_render(self):
        for user in [self.owner,self.requester,self.approver,self.accountant,self.ceo,self.sales,self.finance]:
            self.signin(user)
            for url in ['/','/requests/','/profile/','/notifications/']:
                response=self.client.get(url)
                self.assertEqual(response.status_code,200,(user.username,url,response.content[:500]))

    def test_role_specific_pages_render(self):
        self.signin(self.ceo)
        for url in ['/queue/','/team/','/team/new/','/operations/','/mail/','/accounting/']:
            self.assertEqual(self.client.get(url).status_code,200,url)
        self.signin(self.requester)
        self.assertEqual(self.client.get('/requests/new/').status_code,200)

    def test_login_case_insensitive_and_logout_post_only(self):
        response=self.client.post('/login/',{'username':'REQUESTER','password':'TestPass!234'})
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.client.get('/logout/').status_code,405)
        self.assertEqual(self.client.post('/logout/').status_code,302)

    def test_login_rate_limit(self):
        for _ in range(16): self.client.post('/login/',{'username':'missing','password':'wrong'})
        response=self.client.post('/login/',{'username':'missing','password':'wrong'})
        self.assertContains(response,'Too many login attempts')

    def test_csrf_protection_on_state_changes(self):
        browser=Client(enforce_csrf_checks=True);browser.force_login(self.owner,backend='portal.auth.LocalBackend')
        self.assertEqual(browser.post('/notifications/read/').status_code,403)
        self.assertEqual(browser.post('/api/push/subscribe/',data='{}',content_type='application/json').status_code,403)

    def test_profile_completion_blocks_actions(self):
        self.requester.phone='';self.requester.save();self.signin(self.requester)
        self.assertRedirects(self.client.get('/'),'/profile/?complete=1',fetch_redirect_response=False)
        response=self.client.post('/api/push/subscribe/',data='{}',content_type='application/json')
        self.assertEqual(response.status_code,403)

    def test_passport_is_encrypted_in_database(self):
        with connection.cursor() as cursor:
            cursor.execute('SELECT passport_number FROM portal_user WHERE id=%s',[self.owner.pk]);value=cursor.fetchone()[0]
        self.assertNotIn('PA1234567',value)
        self.owner.refresh_from_db();self.assertEqual(self.owner.passport_number,'PA1234567')

    def test_cross_company_request_is_hidden(self):
        self.signin(self.outsider)
        self.assertEqual(self.client.get(reverse('request_detail',args=[self.req.pk])).status_code,404)
        self.assertFalse(visible_requests(self.outsider).exists())

    def test_unassigned_sales_can_only_view_queue_summary(self):
        self.signin(self.sales)
        self.assertContains(self.client.get('/queue/'),self.req.reference)
        self.assertEqual(self.client.get(reverse('request_detail',args=[self.req.pk])).status_code,404)
        self.assertFalse(visible_requests(self.sales).exists())

    def test_claim_is_exclusive(self):
        workflow.claim_request(self.sales,self.req.pk)
        with self.assertRaises(ValidationError): workflow.claim_request(self.sales2,self.req.pk)
        self.req.refresh_from_db();self.assertEqual(self.req.assignee,self.sales)

    def test_assigned_sales_cannot_access_others(self):
        workflow.claim_request(self.sales,self.req.pk)
        self.assertTrue(visible_requests(self.sales).filter(pk=self.req.pk).exists())
        self.assertFalse(visible_requests(self.sales2).filter(pk=self.req.pk).exists())

    def test_reassignment_removes_old_assignee_access(self):
        workflow.claim_request(self.sales,self.req.pk)
        workflow.reassign_request(self.ceo,self.req.pk,self.sales2,'Covering leave')
        self.assertFalse(visible_requests(self.sales).filter(pk=self.req.pk).exists())
        self.assertTrue(visible_requests(self.sales2).filter(pk=self.req.pk).exists())

    def test_accountant_has_no_automatic_request_access(self):
        self.assertFalse(visible_requests(self.accountant).exists())
        self.assertFalse(visible_requests(self.finance).exists())

    def test_request_submission_idempotent(self):
        draft=Draft.objects.create(user=self.requester)
        data={'title':'Paris','origin':'Beirut','destination':'Paris','departure':timezone.localdate()+timedelta(days=30),
            'return_date':None,'travellers':1,'budget':'','requirements':'','traveller_details':''}
        first=workflow.submit_request(self.requester,draft.pk,data)
        second=workflow.submit_request(self.requester,draft.pk,data)
        self.assertEqual(first.pk,second.pk)
        self.assertEqual(Delivery.objects.filter(dedupe_key__contains='business').count(),1)

    def test_accountant_cannot_submit_request(self):
        draft=Draft.objects.create(user=self.accountant)
        with self.assertRaises(PermissionDenied): workflow.submit_request(self.accountant,draft.pk,{})

    def test_request_dates_validated(self):
        form=RequestForm({'title':'Trip','origin':'BEY','destination':'BKK','departure':'2000-01-01','travellers':0})
        self.assertFalse(form.is_valid());self.assertIn('departure',form.errors);self.assertIn('travellers',form.errors)

    def test_quote_page_and_pdf_render(self):
        quote=self.quote();self.signin(self.requester)
        self.assertContains(self.client.get(reverse('request_detail',args=[self.req.pk])),'Your quotation')
        response=self.client.get(reverse('quote_download',args=[self.req.pk,quote.pk]))
        self.assertEqual(response.status_code,200);self.assertTrue(b''.join(response.streaming_content).startswith(b'%PDF'))

    def test_sales_quote_creation_page(self):
        self.quote();self.signin(self.sales)
        self.assertEqual(self.client.get(reverse('quote_create',args=[self.req.pk])).status_code,200)

    def test_quote_cannot_be_sent_by_unassigned_sales(self):
        with self.assertRaises(PermissionDenied): workflow.issue_quote(self.sales2,self.req.pk,{})

    def test_no_approvers_does_not_autoapprove(self):
        quote=self.quote();User.objects.filter(company=self.company).update(can_approve=False)
        with self.assertRaises(ValidationError): workflow.request_approval(self.requester,self.req.pk,quote.pk)
        self.req.refresh_from_db();self.assertEqual(self.req.status,'quote_sent');self.assertFalse(quote.approvals.exists())

    def test_missing_approver_phone_blocks_submission(self):
        quote=self.quote();self.approver.phone='';self.approver.save()
        with self.assertRaises(ValidationError): workflow.request_approval(self.requester,self.req.pk,quote.pk)

    def test_all_approvers_required_before_booking(self):
        quote=self.awaiting();self.assertEqual(quote.approvals.count(),2)
        workflow.decide(self.owner,self.req.pk,quote.pk,'approved')
        self.req.refresh_from_db();self.assertEqual(self.req.status,'awaiting_approval')
        with self.assertRaises(ValidationError): workflow.change_status(self.sales,self.req.pk,'booking')
        workflow.decide(self.approver,self.req.pk,quote.pk,'approved')
        self.req.refresh_from_db();self.assertEqual(self.req.status,'approved')
        workflow.change_status(self.sales,self.req.pk,'booking')
        with self.assertRaises(ValidationError): workflow.change_status(self.sales,self.req.pk,'confirmed')
        workflow.change_status(self.sales,self.req.pk,'confirmed',booking_reference='SUPPLIER-123')
        workflow.change_status(self.sales,self.req.pk,'closed')
        self.req.refresh_from_db();self.assertEqual(self.req.status,'closed')

    def test_other_company_cannot_approve(self):
        quote=self.awaiting()
        with self.assertRaises(PermissionDenied): workflow.decide(self.outsider,self.req.pk,quote.pk,'approved')

    def test_approver_has_request_access_but_not_passport(self):
        self.awaiting();self.signin(self.approver)
        response=self.client.get(reverse('request_detail',args=[self.req.pk]))
        self.assertEqual(response.status_code,200);self.assertNotContains(response,'PA1234567')
        self.assertNotContains(response,'Private requester details')

    def test_approval_snapshot_does_not_change_with_new_approver(self):
        quote=self.awaiting();new=self.user('late','requester',self.company,True)
        self.assertEqual(quote.approvals.count(),2)
        with self.assertRaises(PermissionDenied): workflow.decide(new,self.req.pk,quote.pk,'approved')

    def test_duplicate_approval_does_not_count_twice(self):
        quote=self.awaiting();workflow.decide(self.owner,self.req.pk,quote.pk,'approved')
        with self.assertRaises(ValidationError): workflow.decide(self.owner,self.req.pk,quote.pk,'approved')
        self.assertEqual(quote.approvals.filter(decision='approved').count(),1)

    def test_rejection_requires_reason_and_blocks_other_decisions(self):
        quote=self.awaiting()
        with self.assertRaises(ValidationError): workflow.decide(self.owner,self.req.pk,quote.pk,'rejected')
        workflow.decide(self.owner,self.req.pk,quote.pk,'rejected','Please change the hotel.')
        self.req.refresh_from_db();self.assertEqual(self.req.status,'rejected')
        with self.assertRaises(ValidationError): workflow.decide(self.approver,self.req.pk,quote.pk,'approved')

    def test_quote_revision_requires_fresh_approvals(self):
        old=self.awaiting();workflow.decide(self.owner,self.req.pk,old.pk,'approved')
        current=self.quote();old.refresh_from_db()
        self.assertTrue(old.superseded);self.assertEqual(current.version,2);self.assertFalse(current.approvals.exists())
        with self.assertRaises(Quote.DoesNotExist): workflow.decide(self.approver,self.req.pk,old.pk,'approved')
        workflow.request_approval(self.requester,self.req.pk,current.pk)
        self.assertEqual(current.approvals.filter(decision='pending').count(),2)

    def test_expired_quote_cannot_be_approved_or_booked(self):
        quote=self.awaiting();Quote.objects.filter(pk=quote.pk).update(valid_until=timezone.now()-timedelta(seconds=1))
        with self.assertRaises(ValidationError): workflow.decide(self.owner,self.req.pk,quote.pk,'approved')
        workflow.expire_quotes();self.req.refresh_from_db();self.assertEqual(self.req.status,'expired')

    def test_internal_note_hidden_from_clients(self):
        self.quote();workflow.add_message(self.sales,self.req.pk,'INTERNAL-COST-SECRET',internal=True)
        self.signin(self.requester);self.assertNotContains(self.client.get(reverse('request_detail',args=[self.req.pk])),'INTERNAL-COST-SECRET')
        with self.assertRaises(PermissionDenied): workflow.add_message(self.requester,self.req.pk,'Attempt',internal=True)

    def test_message_deduplication(self):
        self.quote();workflow.add_message(self.requester,self.req.pk,'Hello',token='123')
        workflow.add_message(self.requester,self.req.pk,'Hello',token='123')
        self.assertEqual(Message.objects.filter(request=self.req,body='Hello').count(),1)

    def test_attachment_encrypted_and_scoped(self):
        self.quote()
        file=save_attachment(SimpleUploadedFile('passport.pdf',b'%PDF-1.4 PRIVATE-PASSPORT'),self.requester,req=self.req,sensitive=True)
        with file.file.open('rb') as stream: self.assertNotIn(b'PRIVATE-PASSPORT',stream.read())
        self.assertFalse(can_attachment(self.outsider,file));self.assertTrue(can_attachment(self.sales,file))
        self.signin(self.requester);response=self.client.get(reverse('attachment',args=[file.pk]))
        self.assertIn(b'PRIVATE-PASSPORT',b''.join(response.streaming_content))
        self.signin(self.outsider);self.assertEqual(self.client.get(reverse('attachment',args=[file.pk])).status_code,404)

    def test_unsafe_or_disguised_upload_rejected(self):
        for filename,data in [('danger.html',b'<script>alert(1)</script>'),('fake.pdf',b'<html>not a PDF'),('fake.jpg',b'not an image')]:
            with self.assertRaises(ValidationError): save_attachment(SimpleUploadedFile(filename,data),self.owner,req=self.req)

    def test_role_escalation_rejected(self):
        self.signin(self.owner)
        response=self.client.post('/team/new/',{'first_name':'Evil','last_name':'User','role':'ceo','password':'TestPass!234','is_active':'on'})
        self.assertEqual(response.status_code,200);self.assertFalse(User.objects.filter(first_name='Evil').exists())

    def test_owner_cannot_edit_other_company_user(self):
        self.signin(self.owner);self.assertEqual(self.client.get(reverse('team_edit',args=[self.outsider.pk])).status_code,404)

    def test_user_creation_and_mandatory_fields(self):
        self.signin(self.owner)
        response=self.client.post('/team/new/',{'first_name':'New','last_name':'Person','role':'requester','password':'NewUser!48291','can_approve':'on','is_active':'on'})
        self.assertEqual(response.status_code,302)
        created=User.objects.get(first_name='New');self.assertEqual(created.company,self.company);self.assertTrue(created.can_approve)
        self.assertTrue(created.username.startswith('C001-'));self.assertFalse(created.profile_complete)

    def test_pending_approver_cannot_be_silently_removed(self):
        self.awaiting();self.signin(self.owner)
        response=self.client.post(reverse('team_edit',args=[self.approver.pk]),{'first_name':'Approver','last_name':'Tester','role':'accountant','email':'approver@example.com','phone':'+96170123456','is_active':'on'})
        self.assertContains(response,'pending approvals');self.approver.refresh_from_db();self.assertTrue(self.approver.can_approve)

    def test_financial_permissions(self):
        self.signin(self.requester);self.assertEqual(self.client.get('/accounting/').status_code,403)
        self.signin(self.accountant);self.assertEqual(self.client.get('/accounting/?company='+str(self.other.pk)).status_code,404)
        self.signin(self.sales);self.assertEqual(self.client.get('/accounting/').status_code,403)

    @patch('portal.views.bridge_call')
    def test_financial_statement_and_pdf(self,bridge):
        bridge.return_value={'rows':[],'debit':'10','credit':'4','closing':'6','currency':'USD'}
        self.signin(self.accountant)
        response=self.client.get('/accounting/');self.assertContains(response,'Closing balance')
        response=self.client.get('/accounting/?download=pdf');self.assertTrue(b''.join(response.streaming_content).startswith(b'%PDF'))

    def test_accounting_provision_idempotent_no_password_copy(self):
        import uuid
        item={'id':str(uuid.uuid4()),'account_number':'ERP100','name':'ERP company','active':True,'version':'opaque','email':'erp@example.com'}
        first=provision(item);second=provision(item)
        self.assertEqual(first.pk,second.pk);self.assertFalse(second.has_usable_password());self.assertTrue(second.is_primary)
        item['active']=False;provision(item);first.refresh_from_db();self.assertFalse(first.is_active)

    @override_settings(ACCOUNTING_ENABLED=True)
    @patch('portal.auth.bridge_call')
    def test_primary_login_uses_accounting_credentials(self,bridge):
        import uuid
        bridge.return_value={'id':str(uuid.uuid4()),'account_number':'ERP200','name':'ERP company','active':True,'version':'version1'}
        response=self.client.post('/login/',{'username':'ERP200','password':'CentralPassword'})
        self.assertEqual(response.status_code,302);user=User.objects.get(username='ERP200');self.assertFalse(user.has_usable_password())
        self.assertEqual(self.client.session['accounting_version'],'version1')

    def test_disabled_company_blocks_member_session(self):
        self.signin(self.requester);self.company.active=False;self.company.save()
        self.assertRedirects(self.client.get('/'),'/login/',fetch_redirect_response=False)

    @override_settings(ACCOUNTING_ENABLED=True)
    @patch('portal.middleware.check_company',side_effect=AccountingUnavailable('Offline'))
    def test_accounting_outage_fails_closed(self,check):
        self.signin(self.requester);self.assertEqual(self.client.get('/').status_code,503)

    @override_settings(AI_ENABLED=True,OPENAI_API_KEY='test-key-not-real',AI_MONTHLY_LIMIT_USD=20)
    def test_ai_budget_reservation_caps_concurrent_allowance(self):
        for _ in range(57): reserve(self.requester)
        with self.assertRaises(AssistantUnavailable): reserve(self.requester)
        budget=AIBudget.objects.get();self.assertLessEqual(budget.reserved+budget.spent,Decimal('20'))

    @override_settings(AI_ENABLED=True,OPENAI_API_KEY='test-key-not-real',AI_MONTHLY_LIMIT_USD=20)
    def test_ai_budget_settlement_idempotent(self):
        call=reserve(self.requester);data={'usage':{'input_tokens':1000,'output_tokens':500},'output':[{'type':'web_search_call'}]}
        settle(call,data);budget=AIBudget.objects.get();cost=budget.spent
        settle(call,data);budget.refresh_from_db();self.assertEqual(budget.spent,cost);self.assertEqual(budget.reserved,0)

    @override_settings(AI_ENABLED=True,OPENAI_API_KEY='test-key-not-real')
    @patch('portal.ai.requests.post')
    def test_ai_uses_limited_public_context_and_citations(self,post):
        post.return_value=Mock(raise_for_status=lambda:None,json=lambda:{'status':'completed','usage':{'input_tokens':100,'output_tokens':20},'output':[{'type':'message','content':[{'type':'output_text','text':'Explore Bangkok.','annotations':[{'type':'url_citation','url':'https://example.com/flights','title':'Flight source'}]}]}]})
        result=generate(self.requester,[{'role':'user','content':'My passport number: PA1234567. Bangkok from Beirut.'}])
        payload=post.call_args.kwargs['json']
        self.assertNotIn('PA1234567',json.dumps(payload));self.assertEqual(payload['max_tool_calls'],2);self.assertFalse(payload['store'])
        self.assertEqual(result['sources'][0]['title'],'Flight source')

    @override_settings(AI_ENABLED=True,OPENAI_API_KEY='test-key-not-real')
    @patch('portal.ai.requests.post')
    def test_uncertain_ai_outcome_keeps_reservation(self,post):
        import requests
        post.side_effect=requests.Timeout()
        with self.assertRaises(AssistantUnavailable):generate(self.requester,[{'role':'user','content':'Bangkok'}])
        self.assertEqual(AIBudget.objects.get().reserved,Decimal('0.35'))

    def test_disabled_ai_keeps_manual_request_available(self):
        self.signin(self.requester);draft=Draft.objects.create(user=self.requester)
        response=self.client.post(reverse('assistant',args=[draft.pk]),data=json.dumps({'message':'Bangkok'}),content_type='application/json')
        self.assertEqual(response.status_code,503);self.assertContains(self.client.get('/requests/new/'),'Submit request')

    def test_push_ssrf_protection(self):
        for url in ['http://fcm.googleapis.com/test','https://localhost/test','https://169.254.169.254/','https://fcm.googleapis.com.evil.test/x','https://user@fcm.googleapis.com/x']:
            self.assertFalse(safe_push_endpoint(url),url)
        self.assertTrue(safe_push_endpoint('https://fcm.googleapis.com/fcm/send/abc'))
        self.signin(self.owner)
        response=self.client.post('/api/push/subscribe/',data=json.dumps({'endpoint':'https://localhost/x','keys':{'auth':'123456789','p256dh':'123456789'}}),content_type='application/json')
        self.assertEqual(response.status_code,400)

    @override_settings(EMAIL_ENABLED=True,EMAIL_HOST_PASSWORD='test',EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_outbox_sends_once_and_contains_portal_link(self):
        Delivery.objects.create(channel='email',recipient='test@example.com',dedupe_key='unique',payload={'text':'Please review your quotation.','url':'/requests/123/','reference':'HS-26-ABCDEF12'})
        process_deliveries();process_deliveries()
        self.assertEqual(len(mail.outbox),1);self.assertIn('/requests/123/',mail.outbox[0].body)
        self.assertEqual(Delivery.objects.get().status,'sent')

    def test_email_cannot_approve_or_impersonate_user(self):
        quote=self.awaiting()
        raw=f'From: {self.approver.email}\r\nSubject: Re: [{self.req.reference}] approve\r\nContent-Type: text/plain\r\n\r\nApproved, please book.'.encode()
        ingest_message('1:9',raw);ingest_message('1:9',raw)
        self.assertEqual(MailReview.objects.count(),1)
        self.assertEqual(Approval.objects.get(quote=quote,user=self.approver).decision,'pending')
        self.assertFalse(Message.objects.filter(body__contains='Approved, please book.').exists())

    def test_pwa_does_not_cache_private_pages(self):
        response=self.client.get('/service-worker.js')
        self.assertNotIn(b'cache.put',response.content);self.assertNotIn(b'cache.add',response.content)
        self.assertEqual(self.client.get('/manifest.webmanifest').status_code,200)
