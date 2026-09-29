"""Child process for the accounting bridge's isolated two-application test."""
import json
import os
import sys
from pathlib import Path

root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root))
database=Path(os.environ['HELLOSAMA_ROUNDTRIP_DB'])
fresh=not database.exists()
os.environ.update({'DJANGO_SETTINGS_MODULE':'hellosama.settings','HELLOSAMA_ENV_FILE':str(database.parent/'absent.env'),
    'DJANGO_DEBUG':'True','DJANGO_ALLOWED_HOSTS':'testserver,localhost,127.0.0.1','DB_NAME':'',
    'AI_ENABLED':'False','EMAIL_ENABLED':'False','IMAP_ENABLED':'False','SMS_ENABLED':'False',
    'VAPID_PRIVATE_KEY':'','VAPID_PUBLIC_KEY':'','ACCOUNTING_STATUS_TTL':'0'})
from django.conf import settings
settings.DATABASES['default']['NAME']=database
settings.ACCOUNTING_STATUS_TTL=0
import django
django.setup()
from django.contrib.auth import authenticate
from django.core.management import call_command
from portal.accounting import sync_companies
from portal.models import Company,User

if fresh:call_command('migrate',interactive=False,verbosity=0)
stage=sys.argv[1]
if stage=='created':
    call_command('portal_worker',once=True,verbosity=0)
    owner=User.objects.get(username='ROUNDTRIP01')
    assert owner.role=='owner' and owner.is_primary and owner.can_approve
    assert not owner.has_usable_password()
    assert authenticate(username='roundtrip01',password='RoundTripPass!2389').pk==owner.pk
    sync_companies();assert User.objects.filter(company=owner.company,is_primary=True).count()==1
    User.objects.create_user(username='roundtrip.employee',password='EmployeePass!2948',company=owner.company,role='requester')
elif stage=='reset':
    assert authenticate(username='ROUNDTRIP01',password='RoundTripPass!2389') is None
    assert authenticate(username='ROUNDTRIP01',password='ChangedRoundTrip!7392') is not None
    assert User.objects.filter(is_primary=True).count()==1
elif stage=='disabled':
    sync_companies()
    assert not Company.objects.get(account_number='ROUNDTRIP01').active
    assert authenticate(username='ROUNDTRIP01',password='ChangedRoundTrip!7392') is None
    assert authenticate(username='roundtrip.employee',password='EmployeePass!2948') is None
elif stage=='restored':
    sync_companies()
    assert authenticate(username='ROUNDTRIP01',password='ChangedRoundTrip!7392') is not None
    assert authenticate(username='roundtrip.employee',password='EmployeePass!2948') is not None
else:raise AssertionError('Unknown test stage')
print(json.dumps({'stage':stage,'passed':True}))
