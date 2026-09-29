from datetime import timedelta
from unittest.mock import Mock, patch
import requests
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from . import tests as fixtures, workflow
from .ai import sanitize
from .models import Approval, Delivery, Notification
from .notifications import process_deliveries, check_sms_statuses, send_delivery
from .sms import approval_text, mobile, submit, status, SMSRejected, SMSUncertain


@override_settings(DEBUG=True,ACCOUNTING_ENABLED=False,AI_ENABLED=False,EMAIL_ENABLED=False,IMAP_ENABLED=False,
    SMS_ENABLED=True,SMS_BASE_URL='https://sms.example.com/websmpp',SMS_USERNAME='test-user',SMS_PASSWORD='test-password',
    SMS_SENDER_ID='SamaTours',SMS_ALLOW_HTTP=False,NOTIFICATION_TEST_MODE=False,
    VAPID_PRIVATE_KEY='',VAPID_PUBLIC_KEY='',PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    ALLOWED_HOSTS=['testserver'],REQUIRE_PASSPORT_COPY=False,PUBLIC_URL='https://hellosama-demo.pythonanywhere.com')
class NotificationTests(TestCase):
    setUp=fixtures.PortalTests.setUp
    user=fixtures.PortalTests.user
    request=fixtures.PortalTests.request
    quote=fixtures.PortalTests.quote
    awaiting=fixtures.PortalTests.awaiting
    signin=fixtures.PortalTests.signin

    def test_sms_created_once_for_every_approver_only(self):
        quote=self.awaiting()
        workflow.request_approval(self.requester,self.req.pk,quote.pk)
        items=Delivery.objects.filter(channel='sms')
        self.assertEqual(items.count(),2)
        self.assertCountEqual(items.values_list('notification__user_id',flat=True),[self.owner.pk,self.approver.pk])

    @patch('portal.sms.requests.post')
    def test_submission_uses_post_no_credentials_in_url(self,post):
        post.return_value=Mock(status_code=200,text='2541524')
        self.assertEqual(submit('+961 70 123 456','HelloSama approval test.'),'2541524')
        args,kw=post.call_args
        self.assertEqual(args[0],'https://sms.example.com/websmpp/websms')
        self.assertNotIn('params',kw);self.assertEqual(kw['data']['pass'],'test-password')
        self.assertEqual(kw['data']['mno'],'96170123456');self.assertFalse(kw['allow_redirects'])

    @patch('portal.sms.requests.post')
    def test_provider_rejection_is_sanitized(self,post):
        post.return_value=Mock(status_code=200,text='ERROR - HTTP06 --> Invalid Sender ID private-provider-detail')
        with self.assertRaisesRegex(SMSRejected,'^HTTP06$'): submit('+96170123456','Test')

    @patch('portal.sms.requests.post')
    def test_unknown_submission_not_claimed_delivered(self,post):
        for result in [requests.Timeout(),Mock(status_code=200,text='<html>unknown</html>')]:
            post.side_effect=result if isinstance(result,Exception) else None
            post.return_value=result
            with self.assertRaises(SMSUncertain):submit('+96170123456','Test')

    @override_settings(SMS_BASE_URL='http://sms.example.com/websmpp')
    @patch('portal.sms.requests.post')
    def test_http_requires_explicit_configuration(self,post):
        with self.assertRaisesRegex(SMSRejected,'HTTP_REQUIRES'):submit('+96170123456','Test')
        post.assert_not_called()

    def test_number_and_message_validation(self):
        self.assertEqual(mobile('00961 70 123 456'),'96170123456')
        for number in ['123','70123456,96170000000','+0 123 456 789']:
            with self.assertRaises(SMSRejected):mobile(number)
        for message in ['x'*161,'a&b','ticket#1','مرحبا']:
            with self.assertRaises(SMSRejected):submit('+96170123456',message)

    def test_short_sms_preserves_portal_link(self):
        link='https://hellosama-samatours2026.pythonanywhere.com/n/12345/'
        text=approval_text('Éléonore & a very long employee name',link)
        self.assertLessEqual(len(text),160);self.assertTrue(text.endswith(link));self.assertTrue(text.isascii())
        self.assertNotIn('&',text)

    @patch('portal.sms.submit',return_value='2541524')
    def test_outbox_acceptance_tracks_id_without_resending(self,send):
        self.awaiting();process_deliveries();process_deliveries()
        self.assertEqual(send.call_count,2)
        self.assertEqual(Delivery.objects.filter(channel='sms',status='submitted',provider_message_id='2541524').count(),2)

    @patch('portal.sms.submit',side_effect=SMSUncertain('SMS_SUBMISSION_OUTCOME_UNKNOWN'))
    def test_uncertain_sms_is_not_automatically_retried(self,send):
        self.awaiting();process_deliveries();process_deliveries()
        self.assertEqual(send.call_count,2)
        self.assertEqual(Delivery.objects.filter(channel='sms',status='uncertain').count(),2)

    @patch('portal.sms.submit',side_effect=SMSRejected('HTTP18'))
    def test_known_rejection_is_failed_not_uncertain(self,send):
        self.awaiting();process_deliveries()
        self.assertEqual(Delivery.objects.filter(channel='sms',status='failed',error='HTTP18').count(),2)

    @patch('portal.sms.submit')
    def test_old_quote_and_decided_approvals_are_skipped(self,send):
        quote=self.awaiting();workflow.decide(self.owner,self.req.pk,quote.pk,'approved')
        owner_item=Delivery.objects.get(channel='sms',notification__user=self.owner)
        self.assertEqual(send_delivery(owner_item),'skipped')
        self.quote();process_deliveries();send.assert_not_called()

    @override_settings(NOTIFICATION_TEST_MODE=True,NOTIFICATION_TEST_PHONES=[])
    @patch('portal.sms.submit')
    def test_test_mode_blocks_unlisted_numbers(self,send):
        self.awaiting();process_deliveries();send.assert_not_called()
        self.assertEqual(Delivery.objects.filter(channel='sms',status='test_blocked').count(),2)

    @patch('portal.sms.submit')
    def test_demo_company_never_sends_external_sms(self,send):
        self.company.account_number='DEMO-100';self.company.save()
        self.awaiting();process_deliveries();send.assert_not_called()
        self.assertFalse(Delivery.objects.exclude(status='skipped').exists())

    @patch('portal.sms.status',return_value='DELIVRD')
    def test_delivery_report_distinguishes_delivered(self,get_status):
        item=Delivery.objects.create(channel='sms',recipient='+96170123456',dedupe_key='report',payload={},
            status='submitted',provider_message_id='123')
        check_sms_statuses();item.refresh_from_db()
        self.assertEqual(item.status,'delivered');self.assertEqual(item.provider_status,'DELIVRD')

    @patch('portal.sms.requests.get')
    def test_status_url_has_only_message_id(self,get):
        get.return_value=Mock(text='DELIVRD',raise_for_status=lambda:None)
        self.assertEqual(status('123'),'DELIVRD');self.assertEqual(get.call_args.kwargs['params'],{'respid':'123'})

    def test_notification_link_requires_correct_account_and_survives_login(self):
        note=Notification.objects.create(user=self.owner,request=self.req,text='Review',url=f'/requests/{self.req.pk}/')
        link=reverse('notification_jump',args=[note.pk])
        response=self.client.get(link);self.assertEqual(response.status_code,302)
        response=self.client.post('/login/?next='+link,{'username':self.owner.username,'password':'TestPass!234','next':link})
        self.assertRedirects(response,link,fetch_redirect_response=False)
        self.assertRedirects(self.client.get(link),note.url,fetch_redirect_response=False)
        self.signin(self.outsider);self.assertEqual(self.client.get(link).status_code,404)

    def test_login_cannot_redirect_to_external_site(self):
        response=self.client.post('/login/',{'username':self.owner.username,'password':'TestPass!234','next':'https://evil.example/'})
        self.assertRedirects(response,'/',fetch_redirect_response=False)

    def test_travel_dates_survive_privacy_filter(self):
        result=sanitize('Beirut 2026-11-20 to 2026-11-26. Call +96170123456.',self.requester)
        self.assertIn('2026-11-20',result);self.assertIn('2026-11-26',result);self.assertNotIn('+96170123456',result)
