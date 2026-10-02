"""Regression checks for the guided client planner; no external API calls."""
import json
from datetime import timedelta
from unittest.mock import Mock, patch
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from .tests import PortalTests
from .ai import generate
from .models import Draft, TravelRequest


@override_settings(DEBUG=True, ACCOUNTING_ENABLED=False, AI_ENABLED=True,
    OPENAI_API_KEY='test-only', OPENAI_MODEL='gpt-6-luna', EMAIL_ENABLED=False,
    SMS_ENABLED=False, IMAP_ENABLED=False, VAPID_PRIVATE_KEY='', VAPID_PUBLIC_KEY='',
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'], ALLOWED_HOSTS=['testserver'])
class PlannerTests(TestCase):
    setUp=PortalTests.setUp
    user=PortalTests.user
    request=PortalTests.request
    signin=PortalTests.signin

    def summary(self):
        return dict(title='Bangkok family trip', origin='Beirut', destination='Bangkok',
            departure=str(timezone.localdate()+timedelta(days=30)), return_date='',
            travellers='4', budget='', requirements='2 adults, 1 child, 1 infant. 6 nights.')

    @patch('portal.views.generate')
    def test_summary_does_not_submit_and_review_edits_are_used(self, generate_mock):
        self.signin(self.requester)
        draft=Draft.objects.create(user=self.requester, messages=[{'role':'user','content':'Bangkok for 4 people.'}])
        generate_mock.return_value=self.summary()
        response=self.client.post(reverse('assistant',args=[draft.pk]),
            data=json.dumps({'action':'summary'}),content_type='application/json')
        self.assertEqual(response.status_code,200)
        self.assertFalse(TravelRequest.objects.filter(source_draft=draft).exists())
        draft.refresh_from_db();self.assertEqual(draft.summary['travellers'],'4')
        form=self.summary();form.update(draft_id=str(draft.pk), destination='Phuket')
        response=self.client.post(reverse('new_request'),form)
        self.assertEqual(response.status_code,302)
        req=TravelRequest.objects.get(source_draft=draft)
        self.assertEqual(req.destination,'Phuket');self.assertEqual(req.travellers,4)
        self.assertIn('1 infant',req.requirements);self.assertEqual(req.budget,'')
        self.client.post(reverse('new_request'),form)
        self.assertEqual(TravelRequest.objects.filter(source_draft=draft).count(),1)

    @patch('portal.views.generate')
    def test_conversation_limit_still_allows_summary(self, generate_mock):
        self.signin(self.requester)
        draft=Draft.objects.create(user=self.requester,messages=[{'role':'user','content':'Travel details'}]*40)
        generate_mock.return_value=self.summary()
        url=reverse('assistant',args=[draft.pk])
        self.assertEqual(self.client.post(url,data=json.dumps({'message':'More'}),content_type='application/json').status_code,400)
        self.assertEqual(self.client.post(url,data=json.dumps({'action':'summary'}),content_type='application/json').status_code,200)

    @patch('portal.ai.requests.post')
    def test_summary_retains_early_details_and_does_not_search(self, post):
        post.return_value=Mock(raise_for_status=lambda:None,json=lambda:{'status':'completed',
            'usage':{'input_tokens':500,'output_tokens':100},'output':[{'type':'message',
            'content':[{'type':'output_text','text':json.dumps(self.summary())}]}]})
        messages=[{'role':'user','content':'Start in Beirut with 2 adults, 1 child and 1 infant.'}]
        messages += [{'role':'assistant','content':'A short question.'}]*30
        self.assertEqual(generate(self.requester,messages,summary=True)['travellers'],'4')
        payload=post.call_args.kwargs['json']
        self.assertIn('Start in Beirut',payload['input'][0]['content'])
        self.assertNotIn('tools',payload)
        self.assertIn('Never ask for a budget',payload['instructions'])
        self.assertIn('at most 70 words',payload['instructions'])

    def test_invalid_form_remains_editable_and_private_fields_not_in_ai(self):
        self.signin(self.requester)
        draft=Draft.objects.create(user=self.requester)
        form=self.summary();form.update(draft_id=str(draft.pk),departure='2000-01-01',traveller_details='Private traveller note')
        response=self.client.post(reverse('new_request'),form)
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'data-review-open="true"')
        self.assertContains(response,'Private traveller note')
        self.assertContains(response,'Your request has not been sent')
        self.assertFalse(TravelRequest.objects.filter(source_draft=draft).exists())

    def test_owner_navigation_and_requester_access(self):
        self.signin(self.owner)
        response=self.client.get(reverse('dashboard'))
        self.assertContains(response,'Company requests');self.assertContains(response,'Company users')
        self.signin(self.requester)
        response=self.client.get(reverse('dashboard'))
        self.assertContains(response,'My requests');self.assertNotContains(response,'Company users')
