from unittest.mock import patch
from django.test import TestCase, override_settings
from django.urls import reverse
from portal.models import User, Company, Audit
from portal.accounting import provision
from portal.auth import CompanyBackend


@override_settings(DEBUG=True, ACCOUNTING_ENABLED=False, ALLOWED_HOSTS=['testserver'],
                   PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class AccountManagementTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='admin', password='Original!1234', role='ceo',
            first_name='Sama', last_name='Admin', email='admin@example.com')
        self.member = User.objects.create_user(username='sales', password='Original!1234', role='sales',
            first_name='Sales', last_name='Person', email='sales@example.com')
        self.client.force_login(self.admin)

    def test_reset_invalidates_old_password_and_session(self):
        from django.test import Client
        other = Client()
        other.force_login(self.member)
        response = self.client.post(reverse('team_password', args=[self.member.pk]),
            {'new_password1': 'Changed!78654', 'new_password2': 'Changed!78654'})
        self.assertEqual(response.status_code, 302)
        self.member.refresh_from_db()
        self.assertTrue(self.member.check_password('Changed!78654'))
        self.assertFalse(self.member.check_password('Original!1234'))
        self.assertEqual(other.get('/').status_code, 302)
        self.assertTrue(Audit.objects.filter(action='user_password_reset').exists())

    def test_only_ceo_can_manage_password_or_delete(self):
        self.client.force_login(self.member)
        for action in ['team_password', 'team_delete']:
            self.assertEqual(self.client.post(reverse(action, args=[self.admin.pk])).status_code, 403)

    def test_delete_confirmation_and_self_protection(self):
        url = reverse('team_delete', args=[self.member.pk])
        self.client.get(url)
        self.client.post(url, {'confirm_username': 'wrong'})
        self.member.refresh_from_db()
        self.assertTrue(self.member.is_active)
        self.client.post(reverse('team_delete', args=[self.admin.pk]), {'confirm_username': 'admin'})
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)
        self.client.post(url, {'confirm_username': 'sales'})
        self.member.refresh_from_db()
        self.assertFalse(self.member.is_active)
        self.assertIsNotNone(self.member.removed_at)
        self.assertEqual(self.client.get(reverse('team_edit', args=[self.member.pk])).status_code, 404)

    def test_primary_removal_survives_sync_and_blocks_login(self):
        import uuid
        item = {'id': str(uuid.uuid4()), 'name': 'Client', 'account_number': 'C10', 'active': True, 'version': 'a'}
        owner = provision(item)
        self.client.post(reverse('team_delete', args=[owner.pk]), {'confirm_username': owner.username})
        provision(item)
        owner.refresh_from_db()
        self.assertFalse(owner.is_active)
        with override_settings(ACCOUNTING_ENABLED=True), patch('portal.auth.bridge_call') as bridge:
            self.assertIsNone(CompanyBackend().authenticate(None, username=owner.username, password='anything'))
            bridge.assert_not_called()

    def test_primary_password_uses_bridge_without_storing_local_password(self):
        import uuid
        item = {'id': str(uuid.uuid4()), 'name': 'Client', 'account_number': 'C11', 'active': True, 'version': 'old'}
        owner = provision(item)
        with patch('portal.views.bridge_call', return_value=dict(item, version='new')) as bridge:
            response = self.client.post(reverse('team_password', args=[owner.pk]),
                {'new_password1': 'Changed!78654', 'new_password2': 'Changed!78654'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(bridge.call_args.args[0], 'owner-password')
        owner.refresh_from_db()
        self.assertFalse(owner.has_usable_password())
        self.assertEqual(owner.company.identity_version, 'new')

    def test_pending_work_blocks_deletion_and_history_survives(self):
        from portal.models import TravelRequest, Quote, Approval
        from django.utils import timezone
        company = Company.objects.create(name='Test', account_number='C12')
        req = TravelRequest.objects.create(reference='TEST', company=company, requester=self.admin,
            assignee=self.member, title='Trip', origin='Beirut', destination='Paris', departure=timezone.localdate())
        url = reverse('team_delete', args=[self.member.pk])
        self.client.post(url, {'confirm_username': self.member.username})
        self.member.refresh_from_db()
        self.assertTrue(self.member.is_active)
        req.assignee = None
        req.status = 'awaiting_approval'
        req.save()
        quote = Quote.objects.create(request=req, version=1, amount=100, details='Trip',
            payment_terms='Test', valid_until=timezone.now(), created_by=self.admin)
        approval = Approval.objects.create(quote=quote, user=self.member, name_snapshot='Sales')
        self.client.post(url, {'confirm_username': self.member.username})
        self.member.refresh_from_db()
        self.assertTrue(self.member.is_active)
        approval.decision = 'approved'
        approval.save()
        self.client.post(url, {'confirm_username': self.member.username})
        self.member.refresh_from_db()
        self.assertFalse(self.member.is_active)
        self.assertTrue(Approval.objects.filter(pk=approval.pk).exists())
        self.assertTrue(TravelRequest.objects.filter(pk=req.pk).exists())
