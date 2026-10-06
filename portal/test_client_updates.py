import csv
import json
from datetime import timedelta
from io import BytesIO, StringIO
from unittest.mock import patch, Mock
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from . import tests as fixtures
from .forms import ProfileForm
from .models import Draft, TravelRequest, Message, Notification
from .files import save_attachment
from django.core.files.uploadedfile import SimpleUploadedFile


@override_settings(DEBUG=True,ACCOUNTING_ENABLED=False,AI_ENABLED=False,EMAIL_ENABLED=False,
    SMS_ENABLED=False,IMAP_ENABLED=False,VAPID_PRIVATE_KEY='',VAPID_PUBLIC_KEY='',
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],ALLOWED_HOSTS=['testserver'])
class ClientUpdateTests(TestCase):
    setUp=fixtures.PortalTests.setUp
    user=fixtures.PortalTests.user
    request=fixtures.PortalTests.request
    signin=fixtures.PortalTests.signin
    quote=fixtures.PortalTests.quote
    awaiting=fixtures.PortalTests.awaiting

    def trip_data(self):
        return dict(title='Family trip',origin='Beirut',destination='Athens',departure=str(timezone.localdate()+timedelta(days=30)),
                    return_date='',travellers='3',budget='',requirements='2 adults and 1 child',service_type='flight',traveller_details='')

    def test_expiry_selectors_keep_day_and_legacy_nationality(self):
        form=ProfileForm(instance=self.requester)
        html=str(form['passport_expiry'])
        self.assertLess(html.index('_day'),html.index('_month'))
        self.assertLess(html.index('_month'),html.index('_year'))
        self.assertIn('Lebanese',str(form['nationality']))
        self.assertIn('Lebanon',str(form['nationality']))
        self.assertGreater(len(form.fields['nationality'].widget.choices),240)
        date=timezone.localdate()+timedelta(days=450)
        fields={k:getattr(self.requester,k) for k in ('first_name','last_name','email','phone','passport_number','nationality')}
        fields.update(passport_expiry_day=str(date.day),passport_expiry_month=str(date.month),passport_expiry_year=str(date.year))
        bound=ProfileForm(fields,instance=self.requester)
        self.assertTrue(bound.is_valid(),bound.errors)
        self.assertEqual(bound.cleaned_data['passport_expiry'],date)
        fields['passport_expiry_month']='2';fields['passport_expiry_day']='31'
        self.assertFalse(ProfileForm(fields,instance=self.requester).is_valid())

    def test_drafts_are_separate_owned_and_archivable(self):
        self.signin(self.requester)
        one=self.client.post(reverse('draft_new'));two=self.client.post(reverse('draft_new'))
        self.assertNotEqual(one.url,two.url)
        draft=Draft.objects.filter(user=self.requester).first()
        private=Draft.objects.create(user=self.outsider,summary={'title':'Other company secret'})
        self.assertEqual(self.client.get(reverse('new_request')+'?draft='+str(private.pk)).status_code,404)
        self.assertEqual(self.client.post(reverse('draft_archive',args=[private.pk])).status_code,404)
        self.client.post(reverse('draft_archive',args=[draft.pk]));draft.refresh_from_db();self.assertTrue(draft.archived)
        self.assertEqual(self.client.post(reverse('assistant',args=[draft.pk]),data=json.dumps({'message':'More'}),content_type='application/json').status_code,409)
        self.client.post(reverse('draft_archive',args=[draft.pk]),{'action':'restore'});draft.refresh_from_db();self.assertFalse(draft.archived)

    def test_save_draft_never_stores_private_travellers_in_summary(self):
        self.signin(self.requester);draft=Draft.objects.create(user=self.requester)
        data=self.trip_data();data['traveller_details']='PRIVATE IDENTIFIER'
        response=self.client.post(reverse('draft_save',args=[draft.pk]),data)
        self.assertEqual(response.status_code,200);draft.refresh_from_db()
        self.assertNotIn('traveller_details',draft.summary)
        self.assertEqual(draft.summary['destination'],'Athens')

    def test_batch_requires_all_valid_and_does_not_partially_submit(self):
        self.signin(self.requester)
        drafts=[Draft.objects.create(user=self.requester,summary=self.trip_data()) for _ in range(2)]
        data={'form-TOTAL_FORMS':'2','form-INITIAL_FORMS':'2','form-MIN_NUM_FORMS':'0','form-MAX_NUM_FORMS':'12','draft_id':[str(d.pk) for d in drafts]}
        for i in range(2): data.update({f'form-{i}-{k}':v for k,v in self.trip_data().items()})
        data['form-1-travellers']='0'
        response=self.client.post(reverse('drafts_review'),data)
        self.assertEqual(response.status_code,200)
        self.assertFalse(TravelRequest.objects.filter(source_draft__in=drafts).exists())
        data['form-1-travellers']='3'
        self.assertEqual(self.client.post(reverse('drafts_review'),data).status_code,302)
        self.assertEqual(TravelRequest.objects.filter(source_draft__in=drafts).count(),2)
        self.client.post(reverse('drafts_review'),data)
        self.assertEqual(TravelRequest.objects.filter(source_draft__in=drafts).count(),2)

    def test_batch_rejects_swapped_draft_ids(self):
        self.signin(self.requester)
        draft=Draft.objects.create(user=self.requester,summary=self.trip_data());other=Draft.objects.create(user=self.outsider)
        data={'form-TOTAL_FORMS':'1','form-INITIAL_FORMS':'1','draft_id':str(other.pk)}
        data.update({'form-0-'+k:v for k,v in self.trip_data().items()})
        self.assertContains(self.client.post(reverse('drafts_review'),data),'open drafts changed')
        self.assertFalse(TravelRequest.objects.filter(source_draft=draft).exists())

    def test_request_filters_stay_inside_visibility_and_preserve_queries(self):
        self.request(reference='HS-26-OWNER',requester=self.owner,service_type='hotel',booking_reference='LOOKUP123')
        self.request(reference='HS-26-OTHER',company=self.other,requester=self.outsider,booking_reference='LOOKUP123')
        self.signin(self.owner)
        response=self.client.get('/requests/?q=LOOKUP123&service=hotel&scope=mine')
        self.assertContains(response,'HS-26-OWNER');self.assertNotContains(response,'HS-26-OTHER')
        response=self.client.get('/requests/?date_from=bad')
        self.assertContains(response,'Enter a valid date')

    @patch('portal.client_views.document',return_value=BytesIO(b'%PDF-test'))
    def test_archive_export_does_not_expose_internal_notes_or_private_files(self,document):
        self.awaiting()
        Message.objects.create(request=self.req,author=self.sales,body='INTERNAL SECRET',internal=True)
        public=Message.objects.create(request=self.req,author=self.requester,body='Public message')
        save_attachment(SimpleUploadedFile('private-passport.pdf',b'%PDF-1.4 test'),self.requester,req=self.req,message=public,sensitive=True)
        self.signin(self.approver)
        response=self.client.get(reverse('request_export',args=[self.req.pk])+'?conversation=1')
        self.assertEqual(response.status_code,200)
        content=str(document.call_args)
        self.assertIn('Public message',content);self.assertNotIn('INTERNAL SECRET',content);self.assertNotIn('private-passport.pdf',content)
        self.signin(self.outsider)
        self.assertEqual(self.client.get(reverse('request_export',args=[self.req.pk])).status_code,404)

    def test_edit_stops_once_quote_exists(self):
        self.signin(self.requester)
        data=self.trip_data();data['destination']='Paris'
        self.assertEqual(self.client.post(reverse('request_edit',args=[self.req.pk]),data).status_code,302)
        self.req.refresh_from_db();self.assertEqual(self.req.destination,'Paris')
        self.quote();data['destination']='Madrid'
        self.client.post(reverse('request_edit',args=[self.req.pk]),data)
        self.req.refresh_from_db();self.assertEqual(self.req.destination,'Paris')

    def test_reminders_only_pending_and_rate_limited(self):
        self.awaiting();self.signin(self.requester)
        Notification.objects.all().delete()
        url=reverse('remind_approvers',args=[self.req.pk])
        self.assertEqual(self.client.post(url).status_code,302)
        count=Notification.objects.count();self.assertGreater(count,0)
        self.client.post(url);self.assertEqual(Notification.objects.count(),count)
        self.assertEqual(self.client.get(url).status_code,405)

    def test_travel_overview_is_owner_only_and_uses_confirmed_dates(self):
        today=timezone.localdate()
        self.req.status='confirmed';self.req.departure=today-timedelta(days=1);self.req.return_date=today+timedelta(days=2);self.req.save()
        self.request(reference='HS-26-FOREIGN',company=self.other,requester=self.outsider,status='confirmed',departure=today,return_date=today+timedelta(days=2))
        self.signin(self.owner)
        response=self.client.get(reverse('travel_overview'))
        self.assertContains(response,self.req.reference);self.assertNotContains(response,'HS-26-FOREIGN')
        self.assertEqual(response.context['counts']['current'],1)
        self.signin(self.requester);self.assertEqual(self.client.get(reverse('travel_overview')).status_code,403)

    @patch('portal.views.bridge_call')
    def test_statement_filter_preserves_account_totals_and_csv_is_safe(self,bridge):
        bridge.return_value={'rows':[{'date':'2026-10-01','ref':'=DANGEROUS()','type':'Flight','debit':'100','credit':'0','running_balance':'100'},
                                    {'date':'2026-10-02','ref':'PAY1','type':'Payment','debit':'0','credit':'20','running_balance':'80'}],
                             'debit':'100','credit':'20','closing':'80'}
        self.signin(self.owner)
        response=self.client.get('/accounting/?q=Flight')
        self.assertEqual(response.status_code,200)
        self.assertEqual(len(response.context['data']['rows']),1)
        self.assertEqual(response.context['data']['closing'],'80')
        response=self.client.get('/accounting/?q=Flight&download=csv')
        rows=list(csv.reader(StringIO(response.content.decode('utf-8-sig'))))
        self.assertEqual(rows[1][1],"'=DANGEROUS()")
        self.assertEqual(rows[1][-1],'100')

    def test_team_search_respects_company(self):
        self.signin(self.owner)
        response=self.client.get('/team/?q=Outsider')
        self.assertNotContains(response,'outsider@example.com')
        response=self.client.get('/team/?role=approver')
        self.assertContains(response,'approver@example.com');self.assertNotContains(response,'requester@example.com')

    def test_quick_approval_requires_current_designated_approver(self):
        quote=self.awaiting()
        url=reverse('quick_approval',args=[self.req.pk,quote.pk])
        self.signin(self.approver);self.assertContains(self.client.get(url),'Approve quotation')
        self.signin(self.requester);self.assertNotContains(self.client.get(url),'name="action" value="approved"')
        quote.superseded=True;quote.save()
        self.signin(self.approver);self.assertContains(self.client.get(url),'replaced this offer')
        self.assertNotContains(self.client.get(url),'name="action" value="approved"')

    def test_travel_message_is_scoped_and_replay_safe(self):
        self.req.status='confirmed';self.req.save()
        other=self.request(reference='HS-26-FOREIGN',company=self.other,requester=self.outsider,status='confirmed')
        self.signin(self.owner);url=reverse('travel_message')
        body={'trip':[str(self.req.pk),str(other.pk)],'body':'Travel update','token':'batch-test'}
        self.assertEqual(self.client.post(url,body).status_code,403)
        self.assertFalse(Message.objects.filter(body='Travel update').exists())
        body['trip']=[str(self.req.pk)]
        self.assertEqual(self.client.post(url,body).status_code,302)
        self.client.post(url,body)
        self.assertEqual(Message.objects.filter(body='Travel update').count(),1)

    @override_settings(AI_ENABLED=True,OPENAI_API_KEY='test-only',OPENAI_MODEL='gpt-6-luna')
    @patch('portal.ai.requests.post')
    def test_ai_cards_require_citation_and_are_not_inventory(self,post):
        from .ai import generate
        reply={'content':'These published options need availability confirmation.','options':[
            {'label':'Published flight','detail':'Check flight schedule','source_url':'https://example.com/schedule'},
            {'label':'Invented deal','detail':'Wrong source','source_url':'https://example.net/fake'}]}
        post.return_value=Mock(raise_for_status=lambda:None,json=lambda:{'status':'completed','usage':{'input_tokens':20,'output_tokens':30},
            'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(reply),
                'annotations':[{'type':'url_citation','url':'https://example.com/schedule','title':'Schedule'}]}]}]})
        result=generate(self.requester,[{'role':'user','content':'Suggest flights'}])
        self.assertEqual([c['label'] for c in result['options']],['Published flight'])
        self.assertIn('Never offer invented schedules',post.call_args.kwargs['json']['instructions'])
        self.assertEqual(post.call_args.kwargs['json']['tool_choice'],'required')

    @override_settings(AI_ENABLED=True,OPENAI_API_KEY='test-only',OPENAI_MODEL='gpt-6-luna')
    @patch('portal.ai.requests.post')
    def test_flight_date_followup_requires_search_but_summary_does_not(self,post):
        from .ai import generate
        post.return_value=Mock(raise_for_status=lambda:None,json=lambda:{'status':'completed',
            'usage':{'input_tokens':20,'output_tokens':30},'output':[{'type':'message','content':[
                {'type':'output_text','text':json.dumps({'content':'Checking published schedules.','options':[]})}]}]})
        conversation=[{'role':'user','content':'Which flights go from Beirut to Dubai?'},
                      {'role':'assistant','content':'What date are you travelling?'},
                      {'role':'user','content':'2026-11-18'}]
        generate(self.requester,conversation)
        self.assertEqual(post.call_args.kwargs['json']['tool_choice'],'required')
        self.assertIn('2026-11-18',post.call_args.kwargs['json']['input'][-1]['content'])
        generate(self.requester,conversation,summary=True)
        self.assertNotIn('tools',post.call_args.kwargs['json'])
        self.assertNotIn('tool_choice',post.call_args.kwargs['json'])
        generate(self.requester,[{'role':'user','content':'Two adults and one child.'}])
        self.assertNotIn('tool_choice',post.call_args.kwargs['json'])

    def test_pdf_export_renders_long_conversations(self):
        Message.objects.create(request=self.req,author=self.requester,body='Long travel update. '*400)
        self.signin(self.owner)
        response=self.client.get(reverse('request_export',args=[self.req.pk])+'?conversation=1')
        self.assertEqual(response.status_code,200)
        self.assertTrue(b''.join(response.streaming_content).startswith(b'%PDF'))
