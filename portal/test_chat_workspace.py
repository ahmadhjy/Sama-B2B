import json
from datetime import timedelta
from unittest.mock import Mock, patch
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from . import tests as fixtures
from .models import Draft, TravelRequest
from .chat import estimate


@override_settings(DEBUG=True,ACCOUNTING_ENABLED=False,AI_ENABLED=True,OPENAI_API_KEY='test-only',
    OPENAI_MODEL='gpt-6-luna',EMAIL_ENABLED=False,SMS_ENABLED=False,IMAP_ENABLED=False,
    VAPID_PRIVATE_KEY='',VAPID_PUBLIC_KEY='',PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    ALLOWED_HOSTS=['testserver'])
class ChatWorkspaceTests(TestCase):
    setUp=fixtures.PortalTests.setUp
    user=fixtures.PortalTests.user
    request=fixtures.PortalTests.request
    signin=fixtures.PortalTests.signin
    quote=fixtures.PortalTests.quote
    awaiting=fixtures.PortalTests.awaiting

    def trip(self):
        return dict(title='Dubai trip',service_type='package',origin='Beirut',destination='Dubai',
            departure=str(timezone.localdate()+timedelta(days=30)),return_date='',travellers='2',
            budget='',requirements='2 adults',traveller_details='')

    def draft(self):
        options=[dict(kind=kind,label=kind+' test option',detail='Published fictional test detail',
            source_url='https://example.com/'+kind,price_min=100,price_max=120,currency='USD',price_basis='total')
            for kind in ['flight','hotel']]
        return Draft.objects.create(user=self.requester,summary=self.trip(),messages=[
            {'role':'user','content':'Please show flight and hotel options.'},
            {'role':'assistant','content':'Here are the published choices.','options':options,
             'sources':[{'url':o['source_url'],'title':o['label']} for o in options]}])

    def select(self,draft,index='1:0'):
        return self.client.post(reverse('draft_select',args=[draft.pk]),
            data=json.dumps({'option_id':index,'label':'CLIENT CANNOT OVERRIDE SAVED OPTION'}),content_type='application/json')

    @patch('portal.views.generate')
    def test_choices_survive_summary_save_reload_and_submission(self,generate):
        self.signin(self.requester);draft=self.draft()
        self.assertEqual(self.select(draft).status_code,200)
        self.assertEqual(self.select(draft,'1:1').json()['estimate']['low'],'200')
        generate.return_value={k:v for k,v in self.trip().items() if k!='traveller_details'}
        self.client.post(reverse('assistant',args=[draft.pk]),data=json.dumps({'action':'summary'}),content_type='application/json')
        self.assertEqual(self.client.post(reverse('draft_save',args=[draft.pk]),self.trip()).status_code,200)
        page=self.client.get(reverse('new_request')+'?draft='+str(draft.pk))
        self.assertContains(page,'value="1:0" data-option-id="1:0" checked')
        self.assertNotContains(page,'CLIENT CANNOT OVERRIDE')
        response=self.client.post(reverse('new_request'),dict(self.trip(),draft_id=str(draft.pk)))
        self.assertEqual(response.status_code,302)
        request=TravelRequest.objects.get(source_draft=draft)
        self.assertIn('Preferred flight: flight test option',request.requirements)
        self.assertIn('Preferred hotel: hotel test option',request.requirements)
        self.assertEqual(len(request.messages.filter(kind='ai').get().metadata['options']),2)
        self.assertEqual(self.select(draft).status_code,409)

    def test_selection_is_owned_validated_and_locked_while_replying(self):
        draft=self.draft();self.signin(self.outsider)
        self.assertEqual(self.select(draft).status_code,404)
        self.signin(self.requester)
        for value in ['-1:0','1:-1','100:0','1:100','1:0:2','bad']:
            self.assertEqual(self.select(draft,value).status_code,400)
        draft.ai_busy_until=timezone.now()+timedelta(seconds=60);draft.save()
        self.assertEqual(self.select(draft).status_code,409)
        draft.ai_busy_until=None;draft.messages[1]['sources']=[];draft.save()
        self.assertEqual(self.select(draft).status_code,400)

    @patch('portal.views.generate')
    def test_route_changes_clear_old_preferences(self,generate):
        self.signin(self.requester);draft=self.draft();self.select(draft)
        generate.return_value={'role':'assistant','content':'Looking at Paris.','options':[],
                               'trip':dict(self.trip(),destination='Paris')}
        response=self.client.post(reverse('assistant',args=[draft.pk]),data=json.dumps({'message':'Change destination to Paris'}),content_type='application/json')
        self.assertEqual(response.json()['message']['selections'],{})
        draft.refresh_from_db();self.assertEqual(draft.summary['selections'],{})
        self.assertEqual(self.select(draft).status_code,400)
        page=self.client.get(reverse('new_request')+'?draft='+str(draft.pk))
        self.assertContains(page,'data-stale="true" disabled')

    def test_manual_itinerary_changes_require_fresh_choices(self):
        self.signin(self.requester);draft=self.draft();self.select(draft)
        revised=dict(self.trip(),travellers='3')
        response=self.client.post(reverse('new_request'),dict(revised,draft_id=str(draft.pk)))
        self.assertContains(response,'Route, dates or passengers changed')
        self.assertFalse(TravelRequest.objects.filter(source_draft=draft).exists())
        response=self.client.post(reverse('draft_save',args=[draft.pk]),revised)
        self.assertEqual(response.json()['selections'],{})
        self.assertEqual(response.json()['trip']['travellers'],'3')
        self.assertEqual(self.select(draft).status_code,400)

    def test_all_drafts_review_is_inside_planning_conversation(self):
        self.signin(self.requester);draft=self.draft()
        response=self.client.get(reverse('new_request')+'?draft='+str(draft.pk)+'&review_all=1')
        html=response.content.decode();start=html.index('id="assistant-messages"');end=html.index('id="assistant-form"')
        self.assertIn('id="batch-review"',html[start:end])
        self.assertIn(reverse('drafts_review'),html[start:end])

    def test_submitted_trip_changes_clear_obsolete_preferences(self):
        self.signin(self.requester);draft=self.draft();self.select(draft)
        self.client.post(reverse('new_request'),dict(self.trip(),draft_id=str(draft.pk)))
        req=TravelRequest.objects.get(source_draft=draft)
        response=self.client.post(reverse('request_edit',args=[req.pk]),dict(self.trip(),destination='Paris',requirements=req.requirements))
        self.assertEqual(response.status_code,302)
        draft.refresh_from_db();req.refresh_from_db()
        self.assertEqual(draft.summary['selections'],{})
        self.assertNotIn('Preferred flight',req.requirements)

    @patch('portal.client_views.document')
    def test_conversation_pdf_preserves_researched_options(self,document):
        from io import BytesIO
        document.return_value=BytesIO(b'test PDF')
        self.signin(self.requester);draft=self.draft()
        self.client.post(reverse('new_request'),dict(self.trip(),draft_id=str(draft.pk)))
        req=TravelRequest.objects.get(source_draft=draft)
        response=self.client.get(reverse('request_export',args=[req.pk])+'?conversation=1')
        self.assertEqual(response.status_code,200)
        text='\n'.join(body for heading,body in document.call_args.args[2])
        self.assertIn('Flight: flight test option',text)
        self.assertIn('Source: https://example.com/flight',text)

    def test_estimates_do_not_mix_unknown_units_or_currencies(self):
        choice=dict(price_min=100,price_max=120,price_basis='per_night',currency='USD')
        self.assertIsNone(estimate({'hotel':choice}))
        self.assertIsNone(estimate({'flight':dict(choice,price_basis='total'),
                                    'hotel':dict(choice,price_basis='total',currency='EUR')}))

    @patch('portal.ai.requests.post')
    def test_research_returns_four_flights_and_three_hotels_with_sources(self,post):
        from .ai import generate
        options=[dict(kind=kind,label=f'{kind} {i}',detail='Dated source details',source_url=f'https://example.com/{kind}/{i}',
            price_min=None,price_max=None,price_basis='unknown',currency='',stars=5 if kind=='hotel' else None)
            for kind,count in [('flight',4),('hotel',3)] for i in range(count)]
        reply={'content':'Choose an option below.','options':options,'trip':self.trip()}
        post.return_value=Mock(raise_for_status=lambda:None,json=lambda:{'status':'completed','usage':{'input_tokens':30,'output_tokens':50},
            'output':[{'type':'web_search_call','action':{'sources':[{'url':o['source_url'],'title':o['label']} for o in options]}},
                      {'type':'message','content':[{'type':'output_text','text':json.dumps(reply)}]}]})
        result=generate(self.requester,[{'role':'user','content':'Find flights and hotels for Dubai.'}])
        self.assertEqual(len(result['options']),7)
        self.assertEqual(result['trip']['destination'],'Dubai')
        self.assertTrue(all(o['price_min'] is None for o in result['options']))
        self.assertEqual(post.call_args.kwargs['json']['include'],['web_search_call.action.sources'])
        self.assertEqual(post.call_args.kwargs['json']['tool_choice'],'required')

    def test_quote_and_approval_controls_are_inside_conversation(self):
        quote=self.awaiting();self.signin(self.approver)
        response=self.client.get(reverse('request_detail',args=[self.req.pk]))
        html=response.content.decode();start=html.index('id="conversation-messages"');end=html.index('class="message-form"')
        self.assertIn('id="current-quotation"',html[start:end])
        self.assertIn('name="action" value="approved"',html[start:end])
        self.signin(self.requester)
        self.assertNotContains(self.client.get(reverse('request_detail',args=[self.req.pk])),'name="action" value="approved"')

    def test_invalid_trip_edit_stays_in_chat(self):
        self.signin(self.requester)
        response=self.client.post(reverse('request_edit',args=[self.req.pk]),dict(self.trip(),travellers='0'))
        self.assertContains(response,'id="edit-trip-details" open')
        self.assertContains(response,'id="conversation-messages"')
        self.req.refresh_from_db();self.assertEqual(self.req.travellers,2)
