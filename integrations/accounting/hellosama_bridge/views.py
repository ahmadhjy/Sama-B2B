"""Signed, server-to-server client portal API. Never exposes ERP-wide serializers."""
import base64
import hashlib
import hmac
import json
import os
import re
import time
from datetime import timedelta
from pathlib import Path
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.http import JsonResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_POST
from accounts_core.models import Client, UserProfile
from portal.data import build_portal_invoice_cards, build_portal_invoice_detail, build_portal_receipts, build_portal_statement
from sales.models import SalesInvoice, SalesInvoiceAttachment
from treasury.models import Payment
from .models import UsedNonce

def secret():
    return os.environ.get('HELLOSAMA_SHARED_SECRET','')

def company_data(profile):
    client=profile.client; user=profile.user
    version=hmac.new(secret().encode(),f'{user.pk}:{user.password}:{user.is_active}:{client.client_code}'.encode(),hashlib.sha256).hexdigest()
    return {'id':str(client.pk),'account_number':client.client_code,'name':client.name_en,
        'email':client.email,'phone':client.phone,'active':bool(user.is_active and profile.is_client_portal),'version':version}

def allowed(request):
    key=secret()
    if len(key)<32 or len(request.body)>32768:
        return False
    stamp=request.headers.get('X-HelloSama-Time','')
    nonce=request.headers.get('X-HelloSama-Nonce','')
    signature=request.headers.get('X-HelloSama-Signature','')
    try:
        if abs(time.time()-int(stamp))>120 or not re.fullmatch(r'[a-f0-9]{32}',nonce): return False
    except ValueError:
        return False
    canonical='\n'.join([request.method,request.path,stamp,nonce,hashlib.sha256(request.body).hexdigest()])
    expected=hmac.new(key.encode(),canonical.encode(),hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected,signature): return False
    try:
        with transaction.atomic(): UsedNonce.objects.create(nonce=nonce)
    except IntegrityError:
        return False
    UsedNonce.objects.filter(created_at__lt=timezone.now()-timedelta(minutes=5)).delete()
    return True

def get_profile(company_id, active=True):
    if not company_id:
        raise Http404()
    filters={'client_id':company_id,'is_client_portal':True}
    if active: filters['user__is_active']=True
    return get_object_or_404(UserProfile.objects.select_related('client','user'),**filters)

def financial(client, data):
    kind=data.get('kind','statement')
    if kind=='statement':
        rows,debit,credit,closing=build_portal_statement(client)
        clean=[{k:v for k,v in r.items() if k not in ('sort_seq','sort_id')} for r in rows]
        return {'rows':clean,'debit':debit,'credit':credit,'closing':closing,'currency':'USD'}
    if kind=='invoices':
        return {'invoices':[{'id':c['invoice'].pk,'number':c['invoice'].invoice_no,'date':c['invoice'].issue_date,
            'total':c['total'],'paid':c['paid'],'remaining':c['remaining'],'currency':'USD','status':c['status_label']}
            for c in build_portal_invoice_cards(client)]}
    if kind=='invoice':
        invoice=get_object_or_404(SalesInvoice,pk=data.get('id'),client=client,status__in=SalesInvoice.reporting_statuses())
        detail=build_portal_invoice_detail(invoice)
        return {'id':invoice.pk,'number':invoice.invoice_no,'date':invoice.issue_date,'lines':detail['lines'],
            'currency':detail['currency'],'totals_currency':'USD','total':detail['total'],'paid':detail['paid'],
            'remaining':detail['remaining'],'schedule':detail['schedule'],
            'attachments':[{'id':a.pk,'name':a.original_name or Path(a.file.name).name} for a in detail['attachments']]}
    if kind=='receipts':
        return {'receipts':build_portal_receipts(client)}
    if kind=='receipt':
        payment=get_object_or_404(Payment,pk=data.get('id'),client=client,party_type=Payment.PartyType.CLIENT,status=Payment.Status.POSTED)
        return {'id':payment.pk,'number':payment.receipt_no,'date':payment.date,'amount':payment.amount,'currency':payment.currency,
            'kind':'Refund issued' if payment.direction==Payment.Direction.OUT else 'Payment received','attachment':bool(payment.attachment_id)}
    raise Http404()

def file_data(client,data):
    if data.get('kind')=='invoice':
        invoice=get_object_or_404(SalesInvoice,pk=data.get('id'),client=client,status__in=SalesInvoice.reporting_statuses())
        attachment=get_object_or_404(SalesInvoiceAttachment,pk=data.get('attachment_id'),invoice=invoice)
        file=attachment.file; name=attachment.original_name or Path(file.name).name
    elif data.get('kind')=='receipt':
        payment=get_object_or_404(Payment,pk=data.get('id'),client=client,party_type=Payment.PartyType.CLIENT,status=Payment.Status.POSTED)
        if not payment.attachment_id: raise Http404()
        file=payment.attachment.file; name=Path(file.name).name
    else: raise Http404()
    try:
        with file.open('rb') as handle: content=handle.read(10*1024*1024+1)
    except (OSError,ValueError): raise Http404()
    if len(content)>10*1024*1024: return {'error':'The source attachment exceeds 10 MB.'}
    return {'name':name,'content':base64.b64encode(content).decode()}

class OwnerAccountError(Exception):
    def __init__(self, code, status=409):
        self.code, self.status = code, status

@sensitive_variables()
@transaction.atomic
def owner_account(data):
    """Enable credentials for an existing client; never reset or re-enable an existing login."""
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError
    from portal.accounts import sync_portal_account
    code = data.get('account_number', '')
    password = data.get('password', '')
    mode = data.get('mode')
    if not isinstance(code, str) or not 1 <= len(code.strip()) <= 64 or mode not in ('create', 'link'):
        raise OwnerAccountError('invalid_request', 400)
    if not isinstance(password, str) or not 1 <= len(password) <= 1024:
        raise OwnerAccountError('invalid_password', 400)
    try:
        client = Client.objects.select_for_update().get(client_code__iexact=code.strip())
    except Client.DoesNotExist:
        raise OwnerAccountError('unknown_client', 404)
    except Client.MultipleObjectsReturned:
        raise OwnerAccountError('account_conflict')
    profile = UserProfile.objects.select_related('user').filter(client=client).first()
    if profile:
        if not profile.is_client_portal or not profile.user.is_active:
            raise OwnerAccountError('disabled_login')
        if not profile.user.check_password(password):
            raise OwnerAccountError('credentials_mismatch')
        # Repeated requests with the same credentials are safe after a lost response.
        return company_data(profile)
    if mode == 'link':
        raise OwnerAccountError('missing_login')
    try:
        validate_password(password)
        if len(password) < 10 or password != password.strip():
            raise ValidationError('Invalid password')
    except ValidationError:
        raise OwnerAccountError('invalid_password', 400)
    try:
        errors = sync_portal_account(client, enabled=True, password=password)
    except IntegrityError:
        raise OwnerAccountError('account_conflict')
    if errors:
        raise OwnerAccountError('account_conflict')
    return company_data(UserProfile.objects.select_related('user', 'client').get(client=client, is_client_portal=True))

@csrf_exempt
@sensitive_post_parameters()
@require_POST
@sensitive_variables('data', 'password')
def endpoint(request,action):
    if not allowed(request):
        return JsonResponse({'error':'Unauthorized'},status=401)
    try:
        data=json.loads(request.body)
        if not isinstance(data,dict): raise ValueError()
    except (ValueError,UnicodeDecodeError):
        return JsonResponse({'error':'Invalid request'},status=400)
    if action=='authenticate':
        account=str(data.get('account_number',''))[:64]; password=data.get('password','')
        if not isinstance(password,str) or len(password)>1024:
            return JsonResponse({'error':'Invalid credentials'},status=401)
        profile=UserProfile.objects.select_related('user','client').filter(client__client_code__iexact=account,is_client_portal=True,user__is_active=True).first()
        if not profile or not profile.user.check_password(password):
            if not profile: get_user_model()().set_password(password)
            return JsonResponse({'error':'Invalid credentials'},status=401)
        result=company_data(profile)
    elif action=='owner-account':
        try:
            result=owner_account(data)
        except OwnerAccountError as exc:
            response=JsonResponse({'error':exc.code},status=exc.status)
            response['Cache-Control']='no-store'
            return response
    elif action=='companies':
        result={'companies':[company_data(p) for p in UserProfile.objects.filter(is_client_portal=True,client__isnull=False).select_related('user','client')]}
    else:
        from django.core.exceptions import ValidationError
        try: profile=get_profile(data.get('company_id'),active=action!='status')
        except (ValidationError,ValueError): return JsonResponse({'error':'Invalid company'},status=400)
        if action=='status': result=company_data(profile)
        elif action=='finance': result=financial(profile.client,data)
        elif action=='file': result=file_data(profile.client,data)
        else: raise Http404()
    response=JsonResponse(result)
    response['Cache-Control']='no-store'
    return response
