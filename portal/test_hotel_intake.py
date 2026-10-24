import json
from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch
from django.test import SimpleTestCase,TestCase,override_settings
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone
from . import hotel_intake as intake, hotel_search, providers, concierge, tests as fixtures
from .models import Draft,TravelRequest


class HotelIntakeLogicTests(SimpleTestCase):
    def trip(self):
        start=timezone.localdate()+timedelta(days=30)
        return {'destination':'Munich','departure':str(start),'return_date':str(start+timedelta(days=4)),
            'travellers':'3','journey':{'services':['hotel'],'passengers':{'adults':2,'children':1,'infants':0},
                'context':{'city_id':'34','city_name':'Munich','country':'DE','nationality':'LB'}}}

    def test_hotel_only_does_not_require_an_origin_or_optional_filters(self):
        trip=self.trip();intake.apply(trip,{'room_count':1,'child_ages':[4]});intake.prepare(trip)
        self.assertTrue(intake.state(trip)['ready']);self.assertEqual(concierge.state(trip)['step'],'hotel_options')
        self.assertEqual(trip['journey']['details']['hotel']['rooms'],[{'adults':2,'childrenAges':[4]}])
        self.assertNotIn('hotel_criteria',trip['journey']);self.assertFalse(trip.get('origin'))

    def test_partial_answers_are_saved_and_only_missing_child_ages_are_asked(self):
        trip=self.trip();intake.apply(trip,{'room_count':1});intake.prepare(trip)
        self.assertEqual(intake.state(trip)['field'],'age')
        reply=intake.direct(trip,'4 years old');intake.apply(trip,reply);intake.prepare(trip)
        self.assertTrue(intake.state(trip)['ready'])
        self.assertEqual(trip['journey']['hotel_intake']['child_ages'],[4])

    def test_room_count_changes_reuse_known_ages_and_nationality(self):
        trip=self.trip();intake.apply(trip,{'room_count':1,'child_ages':[4]});intake.prepare(trip)
        intake.apply(trip,{'room_count':2});intake.prepare(trip)
        self.assertEqual(intake.state(trip)['field'],'room')
        self.assertEqual(intake.saved(trip)['child_ages'],[4])
        intake.apply(trip,{'room':2});intake.prepare(trip)
        self.assertEqual(trip['journey']['details']['hotel']['rooms'],[{'adults':1,'childrenAges':[]},{'adults':1,'childrenAges':[4]}])

    def test_invalid_room_occupancy_fails_before_search(self):
        trip=self.trip();trip['journey']['passengers']={'adults':3,'children':0,'infants':0};trip['travellers']='3'
        intake.apply(trip,{'room_count':2})
        with self.assertRaises(ValidationError): intake.apply(trip,{'room_adults':3})

    def test_complete_rooms_must_match_adult_and_child_counts(self):
        with self.assertRaises(ValidationError):
            intake.apply(self.trip(),{'rooms':[{'adults':1,'childrenAges':[4,5]}]})

    def test_child_age_correction_reuses_the_room_and_dates(self):
        trip=self.trip();intake.apply(trip,{'room_count':1,'child_ages':[4]});intake.prepare(trip)
        intake.apply(trip,{'age':5});intake.prepare(trip)
        self.assertEqual(trip['journey']['details']['hotel']['rooms'],[{'adults':2,'childrenAges':[5]}])
        self.assertTrue(intake.state(trip)['ready'])

    def test_conflicting_dates_and_duration_are_not_silently_accepted(self):
        with self.assertRaises(ValidationError): intake.apply(self.trip(),{'check_out':self.trip()['return_date'],'nights':2})

    def test_hotel_dates_can_differ_without_changing_other_services(self):
        trip=self.trip();trip['journey']['services']=['flight','hotel'];old=deepcopy(trip)
        start=timezone.localdate()+timedelta(days=31)
        intake.apply(trip,{'check_in':str(start),'check_out':str(start+timedelta(days=2))})
        self.assertEqual(trip['departure'],old['departure']);self.assertEqual(trip['return_date'],old['return_date'])
        self.assertEqual(intake.saved(trip)['check_in'],str(start))

    def test_anywhere_is_not_an_invented_landmark_and_anything_broadens_all_preferences(self):
        old={'landmark':'Munich city centre','stars':[3,4],'board_basis':'AI','unverified':['Dates to confirm']}
        action=hotel_search.conversational_intent(old,'suggest something within the city',{'landmark':'Marienplatz'})
        self.assertEqual(action['landmark'],'')
        action=hotel_search.conversational_intent(old,'I didnt ask for Marienplatz, just find anything in Munich',{'landmark':'Marienplatz'})
        self.assertEqual(hotel_search.merge(old,action),hotel_search.DEFAULTS)

    def test_broad_words_do_not_drop_new_specific_preferences_or_invent_central_landmarks(self):
        action=hotel_search.conversational_intent({},'any hotel in Munich with breakfast',{'board_basis':'BB'})
        self.assertEqual(action,{'board_basis':'BB','hotel_name':''})
        action=hotel_search.conversational_intent({},'Munich city centre',{'landmark':'Marienplatz'})
        self.assertEqual(action,{'landmark':'city centre'})

    @patch('portal.providers.call')
    @patch('portal.providers.mapping')
    def test_city_qualified_centre_uses_actual_city_coordinates(self,mapping,call):
        call.return_value={'name':'Munich','geolocation':{'latitude':48.137,'longitude':11.575}}
        point=hotel_search.resolve_place(34,{'landmark':'Munich city centre'})
        self.assertEqual(point['latitude'],48.137);mapping.assert_not_called()


@override_settings(DEBUG=True,ACCOUNTING_ENABLED=False,AI_ENABLED=False,EMAIL_ENABLED=False,SMS_ENABLED=False,
    IMAP_ENABLED=False,VAPID_PRIVATE_KEY='',VAPID_PUBLIC_KEY='',PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class HotelConversationTests(TestCase):
    setUp=fixtures.PortalTests.setUp
    user=fixtures.PortalTests.user
    request=fixtures.PortalTests.request
    signin=fixtures.PortalTests.signin

    def post(self,draft,**data):
        return self.client.post(reverse('provider_offers',args=[draft.pk]),json.dumps(dict(kind='hotel',**data)),content_type='application/json')

    def draft(self):
        self.signin(self.requester);return Draft.objects.create(user=self.requester,summary={'service_type':'hotel','journey':{'services':['hotel']}})

    def full_reply(self):
        start=timezone.localdate()+timedelta(days=30)
        return {'role':'assistant','content':'Checking.','hotel_details':{'city':'Istanbul','check_in':str(start),
            'check_out':str(start+timedelta(days=4)),'adults':2,'children':1,'infants':0,'child_ages':[4]},
            'hotel_search':{'hotel_name':'Occidental'}}

    def city(self): return [{'id':2594,'name':'Istanbul','country':'TR','country_name':'Türkiye','exact':True}]

    @patch('portal.providers.hotel_cities')
    @patch('portal.providers.search')
    @patch('portal.views.generate')
    def test_screenshot_bulk_request_keeps_dates_guests_child_age_and_asks_no_origin(self,generate,search,cities):
        draft=self.draft();generate.return_value=self.full_reply();cities.return_value=self.city()
        result=self.post(draft,hotel_message='CHECK FOR ME OCCIDENTAL HOTEL IN ISTANBUL FROM 4 NOV TO 8 NOV 2 ADULTS AND 1 CHILD 4 YEARS')
        self.assertEqual(result.status_code,200,result.content);self.assertEqual(result.json()['guide']['hotel']['field'],'nationality')
        self.assertTrue(generate.call_args.kwargs['hotel_mode']);search.assert_not_called()
        result=self.post(draft,hotel_message='FROM LEBANON')
        self.assertEqual(result.json()['guide']['hotel']['field'],'room_count');self.assertEqual(generate.call_count,1)
        search.return_value=[providers.option('hotel','Occidental hotel','Supplier room',150,'EUR',{'hotel_index':100})]
        result=self.post(draft,hotel_reply={'room_count':1});self.assertEqual(result.status_code,200,result.content)
        self.assertEqual(result.json()['guide']['step'],'hotel_options');self.assertEqual(len(result.json()['message']['options']),1)
        detail=search.call_args.args[1]['journey']['details']['hotel']
        self.assertEqual(detail['rooms'],[{'adults':2,'childrenAges':[4]}]);self.assertEqual(detail['nationality'],'LB')
        self.assertFalse(result.json()['trip'].get('origin'))
        index=result.json()['message']['message_index']
        selected=self.client.post(reverse('draft_select',args=[draft.pk]),json.dumps({'option_id':f'{index}:0'}),content_type='application/json')
        self.assertEqual(selected.status_code,200)
        draft.refresh_from_db();revised,_=concierge.answer(draft.summary,'complete_service',{'service':'hotel'});revised,_=concierge.answer(revised,'notes',{'note':''});draft.summary=revised;draft.save()
        result=self.client.post(reverse('new_request'),dict(concierge.values(revised),draft_id=str(draft.pk)),HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(result.status_code,200,result.content);self.assertTrue(result.json()['submitted'])
        self.assertEqual(TravelRequest.objects.get(source_draft=draft).origin,'')

    @patch('portal.providers.hotel_cities')
    @patch('portal.views.generate')
    def test_partial_hotel_conversation_survives_reload(self,generate,cities):
        draft=self.draft();generate.return_value=self.full_reply();cities.return_value=self.city()
        self.post(draft,hotel_message='Occidental in Istanbul, four nights, 2 adults, child aged 4')
        draft.refresh_from_db();state=concierge.state(draft.summary)
        self.assertEqual(state['hotel']['known']['child_ages'],[4]);self.assertEqual(state['hotel']['field'],'nationality')
        page=self.client.get(reverse('new_request')+'?draft='+str(draft.pk));self.assertContains(page,'nationality')

    @patch('portal.views.generate')
    def test_explanation_does_not_search_or_drop_saved_dates(self,generate):
        draft=self.draft();draft.summary=self.full_reply()['hotel_details'];draft.summary={'journey':{'services':['hotel']},'departure':draft.summary['check_in'],'return_date':draft.summary['check_out']};draft.save()
        generate.return_value={'content':'Nationality affects the supplier’s eligible rates.','hotel_details':None,'hotel_search':None}
        with patch('portal.providers.search') as search:
            result=self.post(draft,hotel_message='Why do you need nationality?')
        self.assertEqual(result.status_code,200);search.assert_not_called();self.assertEqual(result.json()['trip']['return_date'],draft.summary['return_date'])

    @patch('portal.providers.hotel_cities')
    @patch('portal.views.generate')
    def test_intake_answers_do_not_use_the_supplier_search_allowance(self,generate,cities):
        from .auth import allow_attempt
        draft=self.draft();generate.return_value=self.full_reply();cities.return_value=self.city()
        self.post(draft,hotel_message='Occidental Istanbul, 4 to 8 November, 2 adults and a child aged 4')
        for _ in range(30): allow_attempt(f'provider-offers:{self.requester.pk}',30,3600)
        result=self.post(draft,hotel_message='Lebanese')
        self.assertEqual(result.status_code,200);self.assertEqual(result.json()['guide']['hotel']['field'],'room_count')
        with patch('portal.providers.search') as search:
            result=self.post(draft,hotel_reply={'room_count':1})
        self.assertEqual(result.status_code,400);self.assertIn('wait',result.json()['error']);search.assert_not_called()

    def test_hotel_intake_is_owned_and_closed_drafts_cannot_change(self):
        draft=self.draft();self.signin(self.outsider);self.assertEqual(self.post(draft,hotel_reply={'room_count':1}).status_code,404)
        self.signin(self.requester);draft.archived=True;draft.save();self.assertEqual(self.post(draft,prepare=True).status_code,404)
