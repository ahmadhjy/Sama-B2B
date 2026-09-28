from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
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
            'Sama administrator exists':User.objects.filter(role='ceo',is_active=True,company__isnull=True).exists(),
            'Worker has run':WorkerState.objects.filter(name='worker').exists()}
        for label,ready in checks.items():
            self.stdout.write(f'{"OK" if ready else "PENDING"}: {label}')
        self.stdout.write('SMS: postponed. Provider credentials and API documentation are not required for this release.')
        self.stdout.write('These are configuration checks. Live account access and delivery still require end-to-end testing.')
