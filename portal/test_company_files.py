"""Access boundaries and the two new user-facing workflows."""
import uuid
from io import BytesIO
from unittest.mock import Mock, patch
from PIL import Image
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from . import tests as fixtures, workflow
from .accounting import AccountingUnavailable, bridge_call, create_company_owner, provision
from .files import save_attachment
from .forms import CompanyOwnerForm, ProfileForm
from .models import Audit, Company, Draft, User


@override_settings(DEBUG=True, ACCOUNTING_ENABLED=False, AI_ENABLED=False, EMAIL_ENABLED=False,
    IMAP_ENABLED=False, SMS_ENABLED=False, VAPID_PRIVATE_KEY='', VAPID_PUBLIC_KEY='',
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'], ALLOWED_HOSTS=['testserver'])
class CompanyFilesTests(TestCase):
    setUp = fixtures.PortalTests.setUp
    user = fixtures.PortalTests.user
    request = fixtures.PortalTests.request
    signin = fixtures.PortalTests.signin
    quote = fixtures.PortalTests.quote
    awaiting = fixtures.PortalTests.awaiting

    def data(self, **kwargs):
        values = dict(account_number='ERPNEW', mode='create', first_name='New', last_name='Owner',
                      email='new@example.com', phone='+96170112233', password='NewPortalPass!9273')
        values.update(kwargs)
        return values

    def item(self):
        return dict(id=str(uuid.uuid4()), account_number='ERPNEW', name='New client company',
                    active=True, version='test-version', email='accounts@example.com', phone='')

    def test_passport_copy_required_before_planning_and_submission(self):
        self.requester.passport_files.all().delete()
        self.assertFalse(self.requester.profile_complete)
        self.assertTrue(ProfileForm(instance=self.requester).fields['passport_copy'].required)
        self.signin(self.requester)
        self.assertRedirects(self.client.get('/requests/new/'), '/profile/?complete=1', fetch_redirect_response=False)
        draft = Draft.objects.create(user=self.requester)
        with self.assertRaises(PermissionDenied):
            workflow.submit_request(self.requester, draft.pk, {})
        save_attachment(SimpleUploadedFile('passport.pdf', b'%PDF-1.4 TEST'), self.requester, passport_owner=self.requester)
        self.assertTrue(self.requester.profile_complete)
        self.assertFalse(ProfileForm(instance=self.requester).fields['passport_copy'].required)
        self.assertEqual(self.client.get('/requests/new/').status_code, 200)

    def test_sama_staff_do_not_need_passports(self):
        self.assertTrue(self.ceo.profile_complete)
        self.assertNotIn('passport_copy', ProfileForm(instance=self.ceo).fields)

    def test_library_keeps_messages_and_groups_files_quotes_and_passport(self):
        quote = self.quote()
        workflow.add_message(self.requester, self.req.pk, 'Supporting file',
            [SimpleUploadedFile('itinerary.pdf', b'%PDF-1.4 TEST')])
        self.signin(self.requester)
        response = self.client.get(reverse('request_files', args=[self.req.pk]))
        for text in ['itinerary.pdf', 'profile-passport.pdf', quote.reference, 'View in conversation']:
            self.assertContains(response, text)
        self.assertContains(self.client.get(reverse('request_detail', args=[self.req.pk])), 'itinerary.pdf')

    def test_library_hides_internal_and_sensitive_files_from_approvers(self):
        self.awaiting()
        for name, internal, sensitive in [('shared.pdf', False, False), ('staff.pdf', True, False), ('traveller.pdf', False, True)]:
            workflow.add_message(self.sales, self.req.pk, name,
                [SimpleUploadedFile(name, b'%PDF-1.4 TEST')], internal=internal, sensitive=sensitive)
        self.signin(self.approver)
        response = self.client.get(reverse('request_files', args=[self.req.pk]))
        self.assertContains(response, 'shared.pdf')
        for name in ['staff.pdf', 'traveller.pdf', 'profile-passport.pdf', 'Requester’s passport']:
            self.assertNotContains(response, name)
        self.signin(self.requester)
        response = self.client.get(reverse('request_files', args=[self.req.pk]))
        self.assertNotContains(response, 'staff.pdf')
        self.assertContains(response, 'traveller.pdf')
        self.signin(self.sales)
        self.assertContains(self.client.get(reverse('request_files', args=[self.req.pk])), 'staff.pdf')

    def test_other_company_and_unassigned_sales_cannot_access_library(self):
        for user in (self.outsider, self.sales2, self.finance):
            self.signin(user)
            self.assertEqual(self.client.get(reverse('request_files', args=[self.req.pk])).status_code, 404)

    def test_image_preview_is_private_and_pdf_stays_a_download(self):
        self.quote()
        stream = BytesIO(); Image.new('RGB', (4,4), '#163e64').save(stream, format='PNG')
        image = save_attachment(SimpleUploadedFile('hotel.png', stream.getvalue()), self.sales, req=self.req)
        self.signin(self.requester)
        response = self.client.get(reverse('attachment', args=[image.pk])+'?preview=1')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response['Content-Disposition'].startswith('inline;'))
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertEqual(b''.join(response.streaming_content), stream.getvalue())
        pdf = self.requester.passport_files.first()
        response = self.client.get(reverse('attachment', args=[pdf.pk])+'?preview=1')
        self.assertTrue(response['Content-Disposition'].startswith('attachment;'))
        # Consume through the test client's streaming wrapper. Closing the
        # response directly sends request_finished inside TestCase's database
        # transaction and prematurely closes a PostgreSQL connection.
        self.assertTrue(b''.join(response.streaming_content).startswith(b'%PDF-'))
        self.signin(self.outsider)
        self.assertEqual(self.client.get(reverse('attachment', args=[image.pk])+'?preview=1').status_code, 404)
        self.signin(self.sales2)
        self.assertEqual(self.client.get(reverse('attachment', args=[pdf.pk])+'?preview=1').status_code, 404)

    def test_owner_creation_only_for_sama_ceo(self):
        for user in (self.owner, self.sales, self.finance, self.requester):
            self.signin(user)
            self.assertEqual(self.client.get('/companies/').status_code, 403)
            self.assertEqual(self.client.post('/companies/new/', self.data()).status_code, 403)
            with self.assertRaises(PermissionDenied): create_company_owner(user, self.data())

    @patch('portal.accounting.bridge_call')
    def test_create_owner_uses_central_identity_and_audit_without_password(self, bridge):
        bridge.return_value = self.item()
        self.signin(self.ceo)
        response = self.client.post('/companies/new/', self.data())
        self.assertRedirects(response, '/companies/')
        owner = User.objects.get(username='ERPNEW')
        self.assertEqual(owner.role, User.Role.OWNER)
        self.assertTrue(owner.is_primary and owner.can_approve)
        self.assertFalse(owner.has_usable_password())
        self.assertFalse(owner.profile_complete)
        self.assertEqual(owner.first_name, 'New')
        self.assertEqual(str(owner.company.erp_id), bridge.return_value['id'])
        self.assertEqual(owner.company.name, 'New client company')
        self.assertNotIn(self.data()['password'], str(list(Audit.objects.values())))
        self.assertContains(self.client.get('/companies/'), 'ERPNEW')
        provision(bridge.return_value)
        self.assertEqual(User.objects.filter(company=owner.company, is_primary=True).count(), 1)
        owner.refresh_from_db(); self.assertEqual(owner.first_name, 'New')

    @patch('portal.accounting.bridge_call')
    def test_already_synced_empty_owner_is_completed_without_duplicate(self, bridge):
        bridge.return_value = self.item()
        synced = provision(bridge.return_value)
        created = create_company_owner(self.ceo, self.data(mode='link'))
        self.assertEqual(created.pk, synced.pk)
        self.assertEqual(created.first_name, 'New')
        self.assertEqual(Company.objects.filter(account_number='ERPNEW').count(), 1)

    @patch('portal.accounting.bridge_call')
    def test_local_company_or_existing_owner_cannot_be_silently_relinked(self, bridge):
        with self.assertRaises(ValidationError):
            create_company_owner(self.ceo, self.data(account_number=self.company.account_number))
        bridge.assert_not_called()
        item = self.item(); primary = provision(item)
        primary.first_name = 'Original'; primary.save()
        with self.assertRaises(ValidationError): create_company_owner(self.ceo, self.data())
        bridge.assert_not_called()

    @patch('portal.accounting.bridge_call', side_effect=AccountingUnavailable('Accounting unavailable.'))
    def test_outage_leaves_no_partial_company_or_user(self, bridge):
        self.signin(self.ceo)
        self.assertContains(self.client.post('/companies/new/', self.data()), 'Accounting unavailable.')
        self.assertFalse(Company.objects.filter(account_number='ERPNEW').exists())
        self.assertFalse(User.objects.filter(username='ERPNEW').exists())

    def test_create_validates_password_but_link_accepts_legacy_existing_password(self):
        self.assertFalse(CompanyOwnerForm(self.data(password='123')).is_valid())
        self.assertTrue(CompanyOwnerForm(self.data(mode='link', password='legacy')).is_valid())

    @override_settings(ACCOUNTING_ENABLED=True)
    @patch('portal.accounting.requests.post')
    def test_provider_errors_are_mapped_without_exposing_private_details(self, post):
        post.return_value = Mock(status_code=409, json=lambda: {'error':'credentials_mismatch', 'detail':'private-password'})
        with self.assertRaises(ValidationError) as error:
            bridge_call('owner-account', self.data())
        self.assertIn('current password', str(error.exception))
        self.assertNotIn('private-password', str(error.exception))
