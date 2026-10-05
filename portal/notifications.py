import json
from datetime import timedelta
from urllib.parse import urlparse
from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.utils import timezone
from .models import Approval, Delivery, Notification, PushSubscription, TravelRequest, User
from .sms import SMSRejected, SMSUncertain

def participants(req, internal=False):
    ids = set(User.objects.filter(role='ceo', company__isnull=True, is_active=True).values_list('id', flat=True))
    if req.assignee_id:
        ids.add(req.assignee_id)
    if not internal:
        ids.add(req.requester_id)
        ids.update(User.objects.filter(company=req.company, role='owner', is_active=True).values_list('id', flat=True))
        quote=req.quotes.filter(superseded=False).first()
        if quote:
            ids.update(quote.approvals.values_list('user_id', flat=True))
    return User.objects.filter(pk__in=ids, is_active=True)

def notify(req, text, event_key, *, users=None, actor=None, email=False, internal=False, approval_quote=None):
    users = users if users is not None else participants(req, internal)
    for user in users:
        if actor and actor.pk == user.pk:
            continue
        url = f'/requests/{req.pk}/'
        if approval_quote is not None:
            url = f'/requests/{req.pk}/review/{approval_quote.pk}/'
        note = Notification.objects.create(user=user, request=req, text=text[:240], url=url)
        payload = {'text':text, 'url':url, 'reference':req.reference}
        if approval_quote is not None:
            payload.update({'quote_id':str(approval_quote.pk),'requester_name':req.requester.label})
            if settings.SMS_ENABLED and user.phone:
                Delivery.objects.get_or_create(dedupe_key=f'{event_key}:sms:{user.pk}', defaults={
                    'notification':note,'channel':'sms','recipient':user.phone,'payload':payload})
        if email and user.email and user.email_notifications:
            Delivery.objects.get_or_create(dedupe_key=f'{event_key}:email:{user.pk}', defaults={
                'notification':note,'channel':'email','recipient':user.email,'payload':payload})
        if settings.VAPID_PRIVATE_KEY:
            Delivery.objects.get_or_create(dedupe_key=f'{event_key}:push:{user.pk}', defaults={
                'notification':note,'channel':'push','recipient':str(user.pk),'payload':payload})

def business_notice(req, text, event_key, url=None):
    Delivery.objects.get_or_create(dedupe_key=f'{event_key}:business', defaults={
        'channel':'email','recipient':settings.BUSINESS_EMAIL,
        'payload':{'text':text,'url':url or f'/requests/{req.pk}/','reference':req.reference}})

def safe_push_endpoint(endpoint):
    parsed=urlparse(endpoint)
    host=(parsed.hostname or '').lower()
    hosts=['fcm.googleapis.com','updates.push.services.mozilla.com','push.services.mozilla.com','web.push.apple.com','notify.windows.com']
    return parsed.scheme == 'https' and parsed.port in (None,443) and not parsed.username and not parsed.password and any(host == h or host.endswith('.'+h) for h in hosts)

def send_delivery(item):
    # Demo fixtures must never produce messages to real phone numbers or mailboxes.
    reference=item.payload.get('reference')
    if reference and TravelRequest.objects.filter(reference=reference,company__erp_id__isnull=True,
            company__account_number__startswith='DEMO-').exists():
        return 'skipped'
    if item.notification_id:
        user=item.notification.user
        if not user.is_active or user.company_id and not user.company.active:
            return 'skipped'
        if item.notification.request_id:
            from .permissions import visible_requests
            if not visible_requests(user).filter(pk=item.notification.request_id).exists():
                return 'skipped'
    payload=item.payload
    if settings.NOTIFICATION_TEST_MODE:
        if item.channel=='email' and item.recipient.lower() not in settings.NOTIFICATION_TEST_EMAILS:
            return 'test_blocked'
        if item.channel=='sms':
            from .sms import mobile
            if mobile(item.recipient) not in {mobile(v) for v in settings.NOTIFICATION_TEST_PHONES}:
                return 'test_blocked'
        if item.channel=='push':
            return 'test_blocked'
    if item.channel=='sms':
        if not settings.SMS_ENABLED:
            return 'disabled'
        if not item.notification_id or not Approval.objects.filter(quote_id=payload.get('quote_id'),
                user_id=item.notification.user_id,decision='pending',quote__superseded=False,
                quote__valid_until__gt=timezone.now(),quote__request__status='awaiting_approval',
                user__can_approve=True).exists():
            return 'skipped'
        from .sms import approval_text, submit
        link=f'{settings.PUBLIC_URL}/n/{item.notification_id}/'
        item.provider_message_id=submit(item.recipient,approval_text(payload.get('requester_name','A teammate'),link))
        item.provider_status='ACCEPTD';item.provider_checked_at=timezone.now()
        item.save(update_fields=['provider_message_id','provider_status','provider_checked_at'])
        return 'submitted'
    if item.channel == 'email':
        if not settings.EMAIL_ENABLED:
            return 'disabled'
        if not settings.EMAIL_HOST_PASSWORD:
            raise RuntimeError('mail_not_configured')
        ref=payload.get('reference','HelloSama')
        url=settings.PUBLIC_URL+payload['url']
        body=f"{payload['text']}\n\nOpen HelloSama: {url}\n\nReview and approve quotations inside HelloSama. Email replies never approve a quotation.\n\nHelloSama | Sama Tours"
        mail=EmailMessage(f'[{ref}] HelloSama update', body, to=[item.recipient], reply_to=[settings.EMAIL_HOST_USER],
            headers={'Message-ID':f'<hellosama-{item.pk}@{settings.EMAIL_HOST_USER.split("@")[-1]}>'})
        mail.send(fail_silently=False)
        return 'sent'
    if item.channel == 'push':
        if not settings.VAPID_PRIVATE_KEY:
            return 'disabled'
        from pywebpush import webpush, WebPushException
        for sub in PushSubscription.objects.filter(user_id=int(item.recipient)):
            if not safe_push_endpoint(sub.endpoint):
                sub.delete(); continue
            try:
                webpush(subscription_info=sub.subscription,
                    data=json.dumps({'title':'HelloSama update','body':'You have an update in your travel portal.', 'url':payload['url']}),
                    vapid_private_key=settings.VAPID_PRIVATE_KEY, vapid_claims={'sub':settings.VAPID_SUBJECT}, timeout=15)
            except WebPushException as exc:
                if exc.response is not None and exc.response.status_code in (404,410):
                    sub.delete()
                else:
                    raise RuntimeError('push_delivery_failed') from exc
        return 'sent'
    return 'disabled'

def process_deliveries(limit=30):
    now=timezone.now()
    # Do not automatically re-send emails whose final SMTP acknowledgement is unknown.
    Delivery.objects.filter(status='sending', locked_at__lt=now-timedelta(minutes=5)).update(status='uncertain', error='Delivery outcome unknown; review before retry')
    count=0
    for _ in range(limit):
        with transaction.atomic():
            item=Delivery.objects.select_for_update().filter(status='pending',available_at__lte=now).order_by('id').first()
            if not item:
                break
            item.status='sending'; item.locked_at=now; item.attempts+=1; item.save()
        try:
            item.status=send_delivery(item)
            item.error=''
        except SMSRejected as exc:
            item.status='failed';item.error=str(exc)
        except Exception as exc:
            # Once a send has started, a connection error may mean the provider accepted it.
            # Surface this instead of creating duplicate approval messages.
            item.status='uncertain'
            item.error=type(exc).__name__[:100]
        item.save(update_fields=['status','error'])
        count+=1
    return count


def check_sms_statuses(limit=10):
    if not settings.SMS_ENABLED:
        return 0
    from django.db.models import Q
    from .sms import status
    now=timezone.now();count=0
    pending=Delivery.objects.filter(channel='sms',status='submitted').filter(
        Q(provider_checked_at__isnull=True)|Q(provider_checked_at__lt=now-timedelta(minutes=2)))
    for item in pending.order_by('provider_checked_at','id')[:limit]:
        if item.created_at < now-timedelta(days=3):
            item.status='uncertain';item.provider_status='UNKNOWN';item.error='SMS delivery report timed out; do not resend without checking'
        else:
            try:
                item.provider_status=status(item.provider_message_id)
                if item.provider_status=='DELIVRD': item.status='delivered';item.error=''
                elif item.provider_status in ('UNDELIV','EXPIRED','REJECTD','DELETED'):
                    item.status='failed';item.error='SMS_'+item.provider_status
            except (SMSRejected,SMSUncertain) as exc:
                item.error=str(exc)
        item.provider_checked_at=now
        item.save(update_fields=['status','provider_status','provider_checked_at','error']);count+=1
    return count
