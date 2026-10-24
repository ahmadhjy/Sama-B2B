import json
from copy import deepcopy
from datetime import timedelta
from unittest.mock import Mock, patch
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from . import concierge, hotel_search as h, providers, tests as fixtures
from .models import Draft


class HotelFilteringTests(SimpleTestCase):
    def test_fallback_does_not_invert_negative_preferences_or_drop_higher_ratings(self):
        intent=h.basic_intent('4 stars and above with breakfast near Old town')
        self.assertEqual(intent['stars'],[4,5]);self.assertEqual(intent['board_basis'],'BB')
        negative=h.basic_intent('Not near the airport, without breakfast')
        self.assertNotIn('landmark',negative);self.assertNotIn('board_basis',negative)
        self.assertTrue(negative['unverified'])
    def test_refinements_preserve_other_filters_and_reset_does_not_accept_model_coordinates(self):
        first=h.merge({},dict(stars=[4,5],board_basis='BB',landmark='Old town'))
        refined=h.merge(first,dict(landmark='Central Station',latitude=40,longitude=20))
        self.assertEqual(refined['stars'],[4,5]);self.assertEqual(refined['board_basis'],'BB')
        self.assertNotIn('latitude',refined)
        self.assertEqual(h.merge(refined,{'reset':True}),h.DEFAULTS)
        with self.assertRaises(ValidationError):h.merge(first,{'radius_km':float('nan')})

    def test_meals_and_refundability_must_match_every_selected_room(self):
        criterion={'board_basis':'BB','refundability':'refundable'}
        good={'boardBasis':'BB','nonRefundable':False}
        self.assertTrue(h.package_matches([good,good],criterion))
        for bad in ({'boardBasis':'RO','nonRefundable':False},{'boardBasis':'BB'},{}):
            self.assertFalse(h.package_matches([good,bad],criterion))
        self.assertFalse(h.package_matches([],criterion))

    @patch('portal.providers.mapping')
    def test_regional_locations_are_resolved_in_the_correct_city_and_ambiguity_is_not_guessed(self,mapping):
        mapping.return_value=[dict(id=1,cityId=34,name='Central Station',geolocation={'latitude':48.8,'longitude':2.3})]
        self.assertEqual(h.resolve_place(34,{'landmark':'Central Station'})['id'],1)
        mapping.return_value.append(dict(id=2,cityId=34,name='Central Station South',geolocation={'latitude':48.9,'longitude':2.4}))
        with self.assertRaises(h.Clarification) as error:h.resolve_place(34,{'landmark':'Central'})
        self.assertEqual(len(error.exception.places),2)
        with self.assertRaises(h.Clarification):h.resolve_place(99,{'landmark':'Central'})

    @patch('portal.providers.mapping')
    def test_missing_landmark_asks_for_a_name_instead_of_searching_the_whole_city(self,mapping):
        mapping.return_value=[]
        with self.assertRaises(h.Clarification):h.resolve_place(34,{'landmark':'Unknown district'})

    @patch('portal.providers.call')
    @patch('portal.hotel_search.resolve_place')
    def test_destination_search_uses_km_and_filters_and_does_not_repeat_previous_hotels(self,place,call):
        place.return_value=dict(id=7,name='Old town',latitude=48.8,longitude=2.3)
        def response(provider,method,path,**kw):
            if path.endswith('/start'):
                body=kw['json'];self.assertEqual(body['destination']['geofence']['radius'],1.5)
                self.assertEqual(body['filters'],{'classification':[4]})
                return {'status':'COMPLETED','srk':'abc-123','tokens':{'results':'private-token'}}
            if path.endswith('/abc-123'):
                return {'pages':{'total':1},'hotels':[
                    dict(index=i,name='Hotel '+str(i),stars=4,details={'geolocation':{'latitude':48.8+delta,'longitude':2.3}})
                    for i,delta in [(1,0),(2,.001),(3,.1)]]}
            return {'offers':[]}
        call.side_effect=response
        data,props,meta=h.fetch(34,2,'2027-01-01','2027-01-05',[{'adults':2,'childrenAges':[]}],
            {'landmark':'Old town','radius_km':1.5,'stars':[4]},exclude=[1])
        self.assertEqual([r['index'] for r in data['hotels']],[2]);self.assertLess(meta['distances']['2'],1.5)
        self.assertNotIn('private-token',json.dumps(meta));self.assertNotIn('private-token',json.dumps(props))

    @patch('portal.providers.call')
    @patch('portal.hotel_search.resolve_place')
    def test_missing_coordinates_cannot_be_presented_as_verified_nearby_hotels(self,place,call):
        place.return_value=dict(id=7,name='Old town',latitude=48.8,longitude=2.3)
        call.side_effect=[{'status':'COMPLETED','srk':'abc','tokens':{'results':'private'}},
            {'hotels':[{'index':1,'name':'No coordinates','stars':4}]}]
        with self.assertRaises(providers.ProviderUnavailable):h.fetch(34,2,'2027-01-01','2027-01-05',[],{'landmark':'Old town'})


@override_settings(DEBUG=True,ACCOUNTING_ENABLED=False,AI_ENABLED=False,EMAIL_ENABLED=False,SMS_ENABLED=False,
    IMAP_ENABLED=False,VAPID_PRIVATE_KEY='',VAPID_PUBLIC_KEY='',PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class HotelChatTests(TestCase):
    setUp=fixtures.PortalTests.setUp
    user=fixtures.PortalTests.user
    request=fixtures.PortalTests.request
    signin=fixtures.PortalTests.signin

    def draft(self):
        self.signin(self.requester);start=timezone.localdate()+timedelta(days=30)
        return Draft.objects.create(user=self.requester,summary=dict(origin='Beirut',destination='Paris',departure=str(start),
            return_date=str(start+timedelta(days=5)),travellers='2',service_type='package',journey={
                'services':['flight','hotel'],'passengers':{'adults':2,'children':0,'infants':0},
                'details':{'flight':{'cabin':'Economy','airline':''},'hotel':{'country':'FR','city_id':'34','city_name':'Paris',
                    'nationality':'LB','rooms':[{'adults':2,'childrenAges':[]}],'preferences':''}},'completed':['flight']}))

    def offer(self,index=1):
        return providers.option('hotel','Hotel '+str(index),'Breakfast',100,'EUR',{'hotel_index':index},stars=4)

    def search(self,draft,**extra):
        return self.client.post(reverse('provider_offers',args=[draft.pk]),json.dumps(dict(kind='hotel',**extra)),content_type='application/json')

    def chat(self,draft,text):
        return self.client.post(reverse('assistant',args=[draft.pk]),json.dumps({'message':text}),content_type='application/json')

    @patch('portal.providers.search')
    @patch('portal.views.generate')
    def test_followup_runs_actual_search_preserves_filters_and_expires_only_hotels(self,generate,search):
        draft=self.draft();search.return_value=[self.offer()]
        self.assertEqual(self.search(draft,filters={'stars':[4],'board_basis':'BB'}).status_code,200)
        draft.refresh_from_db();draft.summary['selections']={'hotel':draft.messages[0]['options'][0],
            'flight':{'label':'Keep flight','detail':'Published schedule','source_url':'https://example.com/flight'}};draft.save()
        generate.return_value={'role':'assistant','content':'Checking.','hotel_search':{'landmark':'Old town'},'trip':{},'options':[]}
        search.return_value=[self.offer(2)]
        result=self.chat(draft,'Near the old town please')
        self.assertEqual(result.status_code,200,result.content)
        draft.refresh_from_db();c=draft.summary['journey']['hotel_criteria']
        self.assertEqual(c['landmark'],'Old town');self.assertEqual(c['stars'],[4]);self.assertEqual(c['board_basis'],'BB')
        self.assertTrue(draft.messages[0]['options'][0]['expired']);self.assertNotIn('hotel',draft.summary['selections'])
        self.assertIn('flight',draft.summary['selections']);self.assertEqual(search.call_count,2)
        self.assertIn('Old town',result.json()['message']['content'])

    @patch('portal.providers.search')
    def test_more_excludes_previously_shown_properties_and_keeps_current_cards(self,search):
        draft=self.draft();search.return_value=[self.offer(1)]
        self.search(draft);search.return_value=[self.offer(2)]
        result=self.search(draft,more=True);self.assertEqual(result.status_code,200,result.content)
        self.assertEqual(search.call_args.args[2]['_exclude'],[1])
        draft.refresh_from_db();self.assertFalse(draft.messages[0]['options'][0].get('expired',False))

    @patch('portal.providers.search')
    @patch('portal.views.generate')
    def test_typed_preference_is_saved_before_search_and_does_not_repeat_known_filters(self,generate,search):
        draft=self.draft();generate.return_value={'hotel_search':{'stars':[4],'board_basis':'BB'}}
        result=self.search(draft,interpret='Four stars with breakfast')
        self.assertEqual(result.status_code,200,result.content)
        self.assertEqual(result.json()['guide']['hotel_criteria']['stars'],[4])
        self.assertIn('board_basis',result.json()['parsed_preferences']);search.assert_not_called()
        draft.refresh_from_db();self.assertEqual(draft.messages[-2]['content'],'Four stars with breakfast')
        self.assertIsNone(draft.ai_busy_until)

    @patch('portal.providers.search')
    def test_location_clarification_and_selection_are_owned_and_validated(self,search):
        draft=self.draft();search.side_effect=h.Clarification('Which station?',[
            {'id':1,'name':'North station','latitude':48.8,'longitude':2.3}])
        result=self.search(draft,filters={'landmark':'Station'})
        self.assertEqual(result.json()['guide']['hotel_places'],[{'id':1,'name':'North station'}])
        self.assertEqual(self.search(draft,location_id=999).status_code,400)
        search.side_effect=None;search.return_value=[self.offer()]
        self.assertEqual(self.search(draft,location_id=1).status_code,200)
        self.assertEqual(search.call_args.args[1]['journey']['hotel_criteria']['location_id'],1)
        self.signin(self.outsider);self.assertEqual(self.search(draft,location_id=1).status_code,404)

    @patch('portal.providers.search')
    @patch('portal.views.generate')
    def test_failure_and_zero_matches_clear_stale_choices_without_claiming_no_availability(self,generate,search):
        draft=self.draft();search.return_value=[self.offer()];self.search(draft)
        generate.return_value={'role':'assistant','content':'Checking','trip':{},'hotel_search':{'stars':[5]}}
        search.side_effect=providers.ProviderUnavailable('Hotel provider is temporarily unavailable.')
        result=self.chat(draft,'Five star hotels instead')
        self.assertEqual(result.status_code,503);self.assertIn('unavailable',result.json()['error'])
        draft.refresh_from_db();self.assertIsNone(draft.ai_busy_until);self.assertTrue(draft.messages[0]['options'][0]['expired'])
        search.side_effect=None;search.return_value=[]
        result=self.search(draft)
        self.assertEqual(result.status_code,200);self.assertIn('No matching hotels were returned',result.json()['message']['content'])

    @patch('portal.views.generate')
    def test_simple_typed_intake_advances_saved_guide_without_model_or_forms(self,generate):
        self.signin(self.requester);draft=Draft.objects.create(user=self.requester,summary={'journey':{'services':['hotel']}})
        for content,expected in [('Beirut','route'),('Paris','departure'),(str(timezone.localdate()+timedelta(days=30)),'return'),
                ('5 nights','travellers'),('2 adults','hotel')]:
            result=self.chat(draft,content);self.assertEqual(result.status_code,200,result.content)
            self.assertEqual(result.json()['guide']['step'],expected)
        generate.assert_not_called()
        draft.refresh_from_db();self.assertEqual(draft.summary['journey']['passengers'],{'adults':2,'children':0,'infants':0})

    @override_settings(AI_ENABLED=True,OPENAI_API_KEY='test-only',OPENAI_MODEL='gpt-6-luna')
    @patch('portal.ai.requests.post')
    def test_model_has_strict_actions_and_room_details_but_hotel_parser_does_not_search_web(self,post):
        from .ai import generate
        answer={'content':'Checking','options':[],'trip':{},'hotel_search':{'landmark':'Old town'},'guide_reply':None}
        post.return_value=Mock(raise_for_status=lambda:None,json=lambda:{'status':'completed','usage':{'input_tokens':20,'output_tokens':30},
            'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(answer)}]}]})
        result=generate(self.requester,[{'role':'user','content':'Breakfast near the old town'}],hotel_only=True)
        self.assertEqual(result['hotel_search']['landmark'],'Old town')
        payload=post.call_args.kwargs['json'];self.assertNotIn('tools',payload)
        self.assertIn('hotel_search',payload['text']['format']['schema']['required'])
