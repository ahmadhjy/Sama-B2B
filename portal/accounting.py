import hashlib
import hmac
import json
import time
import uuid
from datetime import timedelta
import requests
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from .models import Audit, Company, User, WorkerState

class AccountingUnavailable(Exception):
    pass

@sensitive_variables()
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
        if action == 'owner-account' and response.status_code in (400, 404, 409):
            errors = {
                'unknown_client': 'Client code not found. Add the client in Sama Accounting first, then use their client code here.',
                'missing_login': 'This client has no portal login yet. Choose Create a new company login.',
                'credentials_mismatch': 'This client already has a portal login. Enter its current password to connect it; existing passwords are not changed here.',
                'disabled_login': 'This client login is disabled. Re-enable it in Sama Accounting before connecting it.',
                'invalid_password': 'Choose a stronger password that meets the accounting password rules.',
                'account_conflict': 'This client code is already used by another login. Resolve the conflict in Sama Accounting first.',
            }
            raise ValidationError(errors.get(response.json().get('error'), 'Accounting could not create this company login. Check the client code and try again.'))
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

@sensitive_variables()
def create_company_owner(actor, data):
    """Manage the single accounting identity from HelloSama; never copy its password."""
    from .permissions import is_ceo
    from django.core.exceptions import PermissionDenied
    if not is_ceo(actor):
        raise PermissionDenied()
    code = data['account_number'].strip()
    # Never silently attach a local/demo company or overwrite a populated owner.
    existing = Company.objects.filter(account_number__iexact=code).first()
    if existing:
        owner = existing.users.filter(is_primary=True).first()
        if not existing.erp_id or not owner or owner.first_name or owner.last_name:
            raise ValidationError('This company already exists in HelloSama. Manage its owner through People & access.')
    if User.objects.filter(username__iexact=code).exclude(company=existing, is_primary=True).exists():
        raise ValidationError('This client code is already used by another HelloSama login.')
    item = bridge_call('owner-account', {'account_number': code, 'password': data['password'], 'mode': data['mode']})
    if not item or not item.get('active') or item.get('account_number', '').casefold() != code.casefold():
        raise AccountingUnavailable('Accounting could not confirm this company login. No local account was created.')
    try:
        with transaction.atomic():
            primary = provision(item)
            primary.first_name = data['first_name']
            primary.last_name = data['last_name']
            if data.get('email'): primary.email = data['email']
            if data.get('phone'): primary.phone = data['phone']
            primary.save(update_fields=['first_name', 'last_name', 'email', 'phone'])
            Audit.objects.create(actor=actor, action='company_owner_connected', target=str(primary.company_id),
                                 detail=f'Accounting client code: {primary.company.account_number}; owner: {primary.pk}')
    except IntegrityError as exc:
        raise AccountingUnavailable('Accounting saved the login, but HelloSama found a conflicting account. Check People & access before retrying.') from exc
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
