import json
from datetime import date, timedelta
from unittest.mock import patch, Mock

import requests
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import providers, workflow
from .models import TravelRequest
from . import test_chat_workspace as workspace


class ProviderParsingTests(SimpleTestCase):
    def setUp(self): cache.clear()

    @override_settings(MONTY_ESIM_CURRENCY='USD')
    @patch('portal.providers.call')
    def test_esim_uses_provider_price_and_does_not_purchase(self,call):
        call.return_value={'bundles':[{'bundle_code':'FR1','bundle_name':'France 1GB',
            'gprs_limit':1,'data_unit':'GB','validity':7,'reseller_retail_price':'4.25'}]}
        rows=providers.search('esim',{'travellers':'2'},{'country':'FR'})
        self.assertEqual(rows[0]['price_min'],'4.25')
        self.assertEqual(rows[0]['price_basis'],'per_unit')
        self.assertEqual(call.call_args.args,('monty','GET','/Bundles'))
        self.assertEqual(call.call_args.kwargs['params']['country_code'],'FRA')

    @override_settings(SWAN_IMS_SANDBOX=True)
    @patch('portal.providers.call')
    def test_insurance_keeps_currency_and_requires_complete_exact_deductible_tier(self,call):
        call.return_value={'status':True,'plans':[{'id':3,'name':'Basic','currency_code':'AUD',
            'price':[[{'id':10,'Price':'12.50','Deductible':'0'}],[{'id':11,'Price':'15.00','Deductible':'0'}]]}]}
        rows=providers.insurance('FRA','LBN',date(2027,1,1),date(2027,1,8),[date(1990,1,1),date(1980,1,1)])
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['currency'],'AUD')
        self.assertEqual(rows[0]['price_min'],'27.50')
        self.assertTrue(rows[0]['sandbox'])
        self.assertNotIn('1990',json.dumps(rows))
        call.return_value['plans'][0]['price'][1][0]['Deductible']='1'
        self.assertEqual(providers.insurance('FRA','LBN',date(2027,1,1),date(2027,1,8),[date(1990,1,1),date(1980,1,1)]),[])

    @patch('portal.providers.mapping')
    @patch('portal.providers.call')
    def test_hotel_uses_complete_package_selling_price_not_floor_or_net(self,call,mapping):
        mapping.side_effect=[[{'id':2}],[{'id':100}]]
        call.return_value={'srk':'search-1','tokens':{'results':'private-token'},'hotels':[{
            'index':100,'name':'Hotel','minPrice':{'value':1,'currency':'USD'},'offers':[{
                'id':'a','rooms':[{'roomCode':1,'name':'Double','boardBasis':'BB','nonRefundable':True}],
                'packages':[{'complete':True,'packageCode':'pkg','packageToken':'never-store',
                    'price':{'selling':{'value':120,'currency':'EUR'},'net':{'value':90,'currency':'EUR'}},
                    'packageRooms':[{'roomReferences':[{'roomCode':1,'selected':True,'roomToken':'never-store'}]}]}]}]}]}
        rows=providers.hotels(10,'LB',date(2027,1,1),date(2027,1,5),[{'adults':2,'childrenAges':[]}])
        self.assertEqual(rows[0]['price_min'],'120.00');self.assertEqual(rows[0]['price_basis'],'total')
        self.assertIn('Breakfast',rows[0]['detail']);self.assertIn('Non-refundable',rows[0]['detail'])
        self.assertNotIn('never-store',json.dumps(rows));self.assertNotIn('private-token',json.dumps(rows))
        self.assertEqual(call.call_args.args,('irix','POST','/api/hotels/v1/search/sync'))

    @patch('portal.providers.requests.request')
    def test_errors_never_expose_provider_body_and_redirects_are_not_followed(self,request):
        request.return_value=Mock(status_code=302)
        with self.assertRaises(providers.ProviderUnavailable):providers.request('GET','https://example.com/')
        self.assertFalse(request.call_args.kwargs['allow_redirects'])
        request.side_effect=requests.RequestException('secret password / birth date')
        with self.assertRaises(providers.ProviderUnavailable) as error:providers.request('GET','https://example.com/')
        self.assertNotIn('secret',str(error.exception))

    def test_nonfinite_prices_and_invalid_currency_are_rejected(self):
        for value in ('NaN','Infinity','-1','0','99999999999'):
            self.assertIsNone(providers.option('hotel','Hotel','Room',value,'USD',{}))
        self.assertIsNone(providers.option('hotel','Hotel','Room','1','XXX-invalid',{}))

    def test_invalid_dates_birth_counts_and_occupancy_do_not_call_provider(self):
        trip={'travellers':'2','departure':str(timezone.localdate()+timedelta(days=30)),
              'return_date':str(timezone.localdate()+timedelta(days=35))}
        with patch('portal.providers.call') as call:
            with self.assertRaises(ValidationError):providers.search('insurance',trip,{'country':'FR','residence':'LB','birth_dates':['1990-01-01']})
            with self.assertRaises(ValidationError):providers.search('hotel',trip,{'country':'FR','nationality':'LB','rooms':[{'adults':1}]})
            call.assert_not_called()


@override_settings(DEBUG=True,ACCOUNTING_ENABLED=False,AI_ENABLED=True,OPENAI_API_KEY='test-only',
    OPENAI_MODEL='gpt-6-luna',EMAIL_ENABLED=False,SMS_ENABLED=False,IMAP_ENABLED=False,
    VAPID_PRIVATE_KEY='',VAPID_PUBLIC_KEY='',PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    ALLOWED_HOSTS=['testserver'])
class ProviderWorkflowTests(TestCase):
    setUp=workspace.ChatWorkspaceTests.setUp
    user=workspace.ChatWorkspaceTests.user
    request=workspace.ChatWorkspaceTests.request
    signin=workspace.ChatWorkspaceTests.signin
    quote=workspace.ChatWorkspaceTests.quote
    awaiting=workspace.ChatWorkspaceTests.awaiting
    trip=workspace.ChatWorkspaceTests.trip
    draft=workspace.ChatWorkspaceTests.draft
    select=workspace.ChatWorkspaceTests.select
    # Shared helpers, not the inherited workspace tests (those remain in their own module).
    def provider_offer(self,trip):
        return dict(providers.option('esim','France 1GB','7 days','4','USD',{'bundle_code':'FRA1'},basis='per_unit'),
                    trip_fingerprint=providers.fingerprint(trip))

    @patch('portal.providers.search')
    def test_quote_select_submit_persists_server_snapshot_without_birthdates(self,search):
        self.signin(self.requester);draft=self.draft();search.return_value=[self.provider_offer(draft.summary)]
        url=reverse('provider_offers',args=[draft.pk])
        response=self.client.post(url,json.dumps({'kind':'esim','country':'FR','birth_dates':['1990-01-01']}),content_type='application/json')
        self.assertEqual(response.status_code,200)
        index=response.json()['message']['message_index']
        result=self.select(draft,f'{index}:0')
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json()['selections']['esim']['price_min'],'4.00')
        draft.refresh_from_db();self.assertNotIn('1990',json.dumps(draft.messages))
        response=self.client.post(reverse('new_request'),dict(self.trip(),draft_id=str(draft.pk)))
        self.assertEqual(response.status_code,302)
        req=TravelRequest.objects.get(source_draft=draft)
        self.assertIn('Provider price: 4.00 USD (per_unit)',req.requirements)
        self.assertIn('FRA1',req.requirements)

    @patch('portal.providers.search')
    def test_new_search_expires_same_service_and_clears_selection(self,search):
        self.signin(self.requester);draft=self.draft();search.return_value=[self.provider_offer(draft.summary)]
        url=reverse('provider_offers',args=[draft.pk]);payload=json.dumps({'kind':'esim','country':'FR'})
        first=self.client.post(url,payload,content_type='application/json').json()['message']['message_index']
        self.assertEqual(self.select(draft,f'{first}:0').status_code,200)
        self.client.post(url,payload,content_type='application/json')
        self.assertEqual(self.select(draft,f'{first}:0').status_code,400)
        draft.refresh_from_db();self.assertNotIn('esim',draft.summary['selections'])

    @patch('portal.providers.search')
    def test_owned_busy_and_closed_draft_guard(self,search):
        draft=self.draft();url=reverse('provider_offers',args=[draft.pk]);payload=json.dumps({'kind':'esim','country':'FR'})
        self.signin(self.outsider);self.assertEqual(self.client.post(url,payload,content_type='application/json').status_code,404)
        self.signin(self.requester);draft.ai_busy_until=timezone.now()+timedelta(seconds=30);draft.save()
        self.assertEqual(self.client.post(url,payload,content_type='application/json').status_code,409)
        search.assert_not_called()

    @patch('portal.providers.search')
    def test_provider_failure_releases_lock_and_hides_raw_error(self,search):
        self.signin(self.requester);draft=self.draft();search.side_effect=ValueError('private birth date')
        response=self.client.post(reverse('provider_offers',args=[draft.pk]),json.dumps({'kind':'insurance'}),content_type='application/json')
        self.assertEqual(response.status_code,503);self.assertNotIn('private',response.content.decode())
        draft.refresh_from_db();self.assertIsNone(draft.ai_busy_until)

    def test_expired_and_sandbox_quotes_cannot_be_selected_or_submitted(self):
        self.signin(self.requester);draft=self.draft();offer=self.provider_offer(draft.summary)
        offer['quoted_at']=(timezone.now()-timedelta(minutes=16)).isoformat()
        draft.messages.append({'role':'assistant','options':[offer],'sources':[{'url':offer['source_url']}],'content':'Offers'})
        draft.save();self.assertEqual(self.select(draft,'2:0').status_code,400)
        draft.summary['selections']={'esim':offer};draft.save()
        with self.assertRaises(ValidationError):workflow.submit_request(self.requester,draft.pk,self.trip())
        offer['quoted_at']=timezone.now().isoformat();offer['sandbox']=True;draft.messages[2]['options']=[offer];draft.save()
        self.assertEqual(self.select(draft,'2:0').status_code,400)
