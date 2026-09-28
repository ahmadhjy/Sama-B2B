import hashlib
import hmac
import json
import time
import uuid
from datetime import timedelta
import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from .models import Company, User, WorkerState

class AccountingUnavailable(Exception):
    pass

def bridge_call(action, payload=None):
    if not settings.ACCOUNTING_ENABLED:
        raise AccountingUnavailable('The accounting connection has not been configured.')
    body = json.dumps(payload or {}, separators=(',', ':'), sort_keys=True).encode()
    path = '/hellosama-api/' + action + '/'
    stamp, nonce = str(int(time.time())), uuid.uuid4().hex
    canonical = '\n'.join(['POST', path, stamp, nonce, hashlib.sha256(body).hexdigest()])
    signature = hmac.new(settings.ACCOUNTING_SHARED_SECRET.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    try:
        response = requests.post(settings.ACCOUNTING_BASE_URL + path, data=body,
            headers={'Content-Type': 'application/json', 'X-HelloSama-Time': stamp,
                     'X-HelloSama-Nonce': nonce, 'X-HelloSama-Signature': signature}, timeout=(5, 20), allow_redirects=False)
        if response.status_code == 401:
            return None
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        raise AccountingUnavailable('Accounting is temporarily unavailable. Please try again shortly.') from exc

@transaction.atomic
def provision(item):
    company, _ = Company.objects.update_or_create(erp_id=item['id'], defaults={
        'name': item['name'], 'account_number': item['account_number'], 'active': item['active'],
        'identity_version': item['version'], 'synced_at': timezone.now()})
    primary = User.objects.filter(company=company, is_primary=True).first()
    if primary is None:
        if User.objects.filter(username__iexact=item['account_number']).exists():
            raise AccountingUnavailable('This company login needs administrator attention.')
        primary = User(company=company, is_primary=True, role=User.Role.OWNER, can_approve=True,
                       username=item['account_number'], email=item.get('email', ''), phone=item.get('phone', ''))
        primary.set_unusable_password()
    else:
        primary.username = item['account_number']
    primary.is_active = item['active']
    primary.save()
    return primary

def sync_companies():
    data = bridge_call('companies')
    if not data or 'companies' not in data:
        raise AccountingUnavailable('Accounting rejected the connection.')
    seen = []
    with transaction.atomic():
        for item in data['companies']:
            primary = provision(item)
            seen.append(primary.company_id)
        Company.objects.filter(erp_id__isnull=False).exclude(pk__in=seen).update(active=False, synced_at=timezone.now())
        WorkerState.objects.update_or_create(name='accounting_sync', defaults={'value': {'ok': True, 'companies': len(seen)}})
    return len(seen)

def check_company(company):
    if not company.erp_id:
        return bool(settings.DEBUG and company.active)
    if company.synced_at and company.synced_at > timezone.now() - timedelta(seconds=settings.ACCOUNTING_STATUS_TTL):
        return company.active
    data = bridge_call('status', {'company_id': str(company.erp_id)})
    if not data:
        return False
    provision(data)
    company.refresh_from_db()
    return company.active
