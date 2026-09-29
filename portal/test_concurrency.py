"""Real row-lock tests run by CI against PostgreSQL, not simulated by SQLite."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from unittest import skipUnless
from django.db import connection, connections
from django.test import TransactionTestCase, override_settings
from django.core.exceptions import ValidationError
from django.utils import timezone
from . import tests as fixtures
from . import workflow
from .ai import reserve, AssistantUnavailable
from .models import User, AIBudget

@skipUnless(connection.vendor=='postgresql','Requires PostgreSQL row locks; CI supplies PostgreSQL.')
@override_settings(DEBUG=True,ACCOUNTING_ENABLED=False,AI_ENABLED=False,EMAIL_ENABLED=False,IMAP_ENABLED=False,
    VAPID_PRIVATE_KEY='',VAPID_PUBLIC_KEY='',PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],SMS_ENABLED=False)
class ConcurrencyTests(TransactionTestCase):
    setUp=fixtures.PortalTests.setUp
    user=fixtures.PortalTests.user
    request=fixtures.PortalTests.request
    quote=fixtures.PortalTests.quote
    awaiting=fixtures.PortalTests.awaiting

    def together(self,first,second,work):
        barrier=Barrier(2)
        def run(user_id):
            try:
                user=User.objects.get(pk=user_id)
                barrier.wait(timeout=15)
                return work(user)
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(run,u.pk) for u in (first,second)]
            return [f.result(timeout=30) for f in futures]

    def test_simultaneous_claim_has_one_owner(self):
        def work(user):
            try: workflow.claim_request(user,self.req.pk);return 'claimed'
            except ValidationError:return 'already claimed'
        self.assertCountEqual(self.together(self.sales,self.sales2,work),['claimed','already claimed'])

    def test_simultaneous_approvals_complete_once(self):
        quote=self.awaiting()
        def work(user): workflow.decide(user,self.req.pk,quote.pk,'approved')
        self.together(self.owner,self.approver,work)
        self.req.refresh_from_db();self.assertEqual(self.req.status,'approved')
        self.assertEqual(self.req.messages.filter(body__startswith='All required approvers').count(),1)

    @override_settings(AI_ENABLED=True,OPENAI_API_KEY='test-only',AI_MONTHLY_LIMIT_USD=20)
    def test_simultaneous_reservations_cannot_overspend(self):
        AIBudget.objects.create(month=timezone.now().strftime('%Y-%m'),spent=Decimal('19.60'))
        def work(user):
            try: reserve(user);return 'reserved'
            except AssistantUnavailable:return 'limited'
        self.assertCountEqual(self.together(self.owner,self.requester,work),['reserved','limited'])
        budget=AIBudget.objects.get();self.assertLessEqual(budget.reserved+budget.spent,Decimal('20'))
