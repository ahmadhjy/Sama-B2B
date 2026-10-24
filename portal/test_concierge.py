"""Guided answers are saved and validated independently of the language model."""
import json
from datetime import timedelta
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from . import tests as fixtures
from . import concierge
from .models import Draft, TravelRequest


@override_settings(DEBUG=True,ACCOUNTING_ENABLED=False,AI_ENABLED=False,EMAIL_ENABLED=False,
    SMS_ENABLED=False,IMAP_ENABLED=False,VAPID_PRIVATE_KEY='',VAPID_PUBLIC_KEY='',
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ConciergeTests(TestCase):
    setUp=fixtures.PortalTests.setUp
    user=fixtures.PortalTests.user
    request=fixtures.PortalTests.request
    signin=fixtures.PortalTests.signin

    def step(self,draft,step,values,**extra):
        draft.refresh_from_db()
        return self.client.post(reverse('draft_guide',args=[draft.pk]),
            data=json.dumps({'step':step,'values':values,'version':concierge.state(draft.summary)['version'],**extra}),
            content_type='application/json')

    def basics(self,services=('flight','hotel','transfer','esim','insurance')):
        self.signin(self.requester);draft=Draft.objects.create(user=self.requester)
        steps=[('services',{'services':list(services)}),('route',{'origin':'Beirut','destination':'Paris'}),
            ('departure',{'departure':str(timezone.localdate()+timedelta(days=30))}),
            ('return',{'nights':5}),('travellers',{'adults':2,'children':1,'infants':1})]
        for step,value in steps:self.assertEqual(self.step(draft,step,value).status_code,200)
        return draft

    def test_full_guided_request_and_truthful_submission_receipt(self):
        draft=self.basics()
        for kind in ('flight','hotel','transfer','esim','insurance'):
            self.assertEqual(self.step(draft,'skip_service',{'service':kind}).status_code,200)
        response=self.step(draft,'notes',{'note':'Please check aisle seats.'})
        self.assertEqual(response.json()['guide']['step'],'ready')
        self.assertFalse(TravelRequest.objects.filter(source_draft=draft).exists())
        stale=self.client.post(reverse('new_request'),dict(response.json()['values'],draft_id=str(draft.pk),journey_version='-1'),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(stale.status_code,400);self.assertFalse(TravelRequest.objects.filter(source_draft=draft).exists())
        response=self.client.post(reverse('new_request'),dict(response.json()['values'],draft_id=str(draft.pk)),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code,200);self.assertTrue(response.json()['submitted'])
        req=TravelRequest.objects.get(source_draft=draft)
        self.assertIn('Services: Flights, Hotel, Transfers, eSIM, Travel insurance',req.requirements)
        self.assertIn('2 adults, 1 child, 1 infant',req.requirements)
        self.assertIn('aisle seats',req.requirements);self.assertEqual(req.travellers,4)
        self.assertEqual(response.json()['reference'],req.reference)
        repeated=self.client.post(reverse('new_request'),{'draft_id':str(draft.pk)},HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(repeated.json()['reference'],req.reference)
        self.assertEqual(TravelRequest.objects.filter(source_draft=draft).count(),1)
        self.assertEqual(self.step(draft,'notes',{'note':'Already sent'}).status_code,404)

    def test_guide_is_owned_versioned_and_locked(self):
        draft=self.basics(('flight',))
        self.signin(self.outsider);self.assertEqual(self.step(draft,'notes',{'note':'No'}).status_code,404)
        self.signin(self.requester);self.assertEqual(self.step(draft,'notes',{'note':'No'},version=-1).status_code,409)
        draft.ai_busy_until=timezone.now()+timedelta(seconds=60);draft.save()
        self.assertEqual(self.step(draft,'notes',{'note':'No'}).status_code,409)

    def test_invalid_dates_and_counts_cannot_silently_advance(self):
        self.signin(self.requester);draft=Draft.objects.create(user=self.requester)
        for step,data in [('services',{'services':['unknown']}),('departure',{'departure':'2000-01-01'}),
            ('travellers',{'adults':0,'children':1,'infants':0}),('travellers',{'adults':101,'children':0,'infants':0})]:
            self.assertEqual(self.step(draft,step,data).status_code,400)
        draft.refresh_from_db();self.assertEqual(draft.summary,{})

    def test_end_date_is_needed_for_hotels_but_one_way_flight_is_supported(self):
        draft=self.basics(('hotel',));self.assertEqual(self.step(draft,'return',{'one_way':True}).status_code,400)
        self.step(draft,'services',{'services':['flight']})
        response=self.step(draft,'return',{'one_way':True});self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['trip']['return_date'],'');self.assertTrue(response.json()['guide']['one_way'])

    def test_private_quote_birth_dates_are_never_saved_by_the_guide(self):
        draft=self.basics(('insurance',))
        response=self.step(draft,'insurance',{'country':'FR','residence':'LB','birth_dates':['1990-02-03']*4})
        self.assertEqual(response.status_code,200);draft.refresh_from_db()
        self.assertNotIn('1990-02-03',json.dumps(draft.summary)+json.dumps(draft.messages))
        self.assertEqual(response.json()['guide']['step'],'insurance_options')

    def test_guest_allocation_and_service_edits_invalidate_choices(self):
        draft=self.basics(('hotel',))
        data={'country':'FR','city_id':'34','city_name':'Paris','nationality':'LB','rooms':[{'adults':1,'childrenAges':[]}]}
        self.assertEqual(self.step(draft,'hotel',data).status_code,400)
        data['rooms']=[{'adults':2,'childrenAges':[5,0]}]
        self.assertEqual(self.step(draft,'hotel',data).status_code,200)
        draft.refresh_from_db();draft.summary['selections']={'hotel':{'id':'0:0'}};draft.save()
        response=self.step(draft,'route',{'origin':'Beirut','destination':'Rome'})
        self.assertEqual(response.json()['selections'],{});self.assertNotIn('hotel',response.json()['guide']['details'])

    def test_ajax_validation_failure_does_not_claim_submission(self):
        self.signin(self.requester);draft=Draft.objects.create(user=self.requester)
        response=self.client.post(reverse('new_request'),{'draft_id':str(draft.pk)},HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code,400);self.assertNotIn('submitted',response.json())
        self.assertFalse(TravelRequest.objects.filter(source_draft=draft).exists())

    def test_chat_keeps_explicit_breakdown_and_cannot_advance_with_past_dates(self):
        summary={'travellers':'4','requirements':'2 adults, 1 child, 1 infant.',
            'origin':'Beirut','destination':'Paris','departure':'2000-01-01',
            'journey':{'services':['flight'],'passengers':{'adults':2,'children':0,'infants':0}}}
        concierge.reconcile_ai_trip(summary)
        self.assertEqual(summary['journey']['passengers'],{'adults':2,'children':1,'infants':1})
        self.assertEqual(concierge.state(summary)['step'],'departure')
