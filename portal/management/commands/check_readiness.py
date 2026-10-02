from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone
from datetime import timedelta
from portal.models import WorkerState, User

class Command(BaseCommand):
    help='Report deployment readiness without printing credentials or sending notifications.'
    def handle(self,*args,**options):
        checks={'Production mode':not settings.DEBUG,'PostgreSQL database':connection.vendor=='postgresql',
            'Accounting connection configured':settings.ACCOUNTING_ENABLED,
            'OpenAI key configured':bool(settings.OPENAI_API_KEY),
            'AI enabled':settings.AI_ENABLED,
            'Email credentials configured':bool(settings.EMAIL_HOST_PASSWORD),
            'Email sending enabled':settings.EMAIL_ENABLED,'Email receiving enabled':settings.IMAP_ENABLED,
            'Push keys configured':bool(settings.VAPID_PRIVATE_KEY and settings.VAPID_PUBLIC_KEY),
            'SMS credentials and sender configured':bool(settings.SMS_USERNAME and settings.SMS_PASSWORD and settings.SMS_SENDER_ID),
            'SMS approval alerts enabled':settings.SMS_ENABLED,
            'Sama administrator exists':User.objects.filter(role='ceo',is_active=True,company__isnull=True).exists(),
            'Worker heartbeat within the last 2 minutes':WorkerState.objects.filter(name='worker',updated_at__gte=timezone.now()-timedelta(minutes=2)).exists()}
        for label,ready in checks.items():
            self.stdout.write(f'{"OK" if ready else "PENDING"}: {label}')
        self.stdout.write('Notification recipients: '+('test allowlists only; push suppressed' if settings.NOTIFICATION_TEST_MODE else 'live recipients'))
        if settings.SMS_ENABLED and settings.SMS_BASE_URL.startswith('http://'):
            self.stdout.write('SMS transport: provider HTTP endpoint; portal OTP does not encrypt API traffic.')
        self.stdout.write('These are configuration checks. Live account access and delivery still require end-to-end testing.')
