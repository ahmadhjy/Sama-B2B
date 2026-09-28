import hashlib
from datetime import timedelta
from django.contrib.auth.backends import ModelBackend
from django.db import transaction
from django.utils import timezone
from .accounting import bridge_call, check_company, provision
from .models import User, RateLimit

def allow_attempt(key, maximum=20, seconds=900):
    key = hashlib.sha256(key.encode()).hexdigest()
    now = timezone.now()
    with transaction.atomic():
        row, _ = RateLimit.objects.get_or_create(key=key, defaults={'expires': now + timedelta(seconds=seconds)})
        row = RateLimit.objects.select_for_update().get(pk=row.pk)
        if row.expires <= now:
            row.attempts, row.expires = 0, now + timedelta(seconds=seconds)
        row.attempts += 1
        row.save()
        return row.attempts <= maximum

class CompanyBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        from django.conf import settings
        if not settings.ACCOUNTING_ENABLED or not username or password is None:
            return None
        existing = User.objects.filter(username__iexact=username).first()
        if existing and not existing.is_primary:
            return None
        data = bridge_call('authenticate', {'account_number': username, 'password': password})
        if not data or not data.get('active'):
            return None
        user = provision(data)
        if request:
            request.session['accounting_version'] = data['version']
        return user

class LocalBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or password is None:
            return None
        user = User.objects.filter(username__iexact=username).select_related('company').first()
        if not user:
            User().set_password(password)
            return None
        if user.is_primary or not user.is_active or not user.check_password(password):
            return None
        if user.company_id and not check_company(user.company):
            return None
        return user
