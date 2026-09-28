import json
from datetime import timedelta
from urllib.parse import urlparse
from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.utils import timezone
from .models import Delivery, Notification, PushSubscription, User

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

def notify(req, text, event_key, *, users=None, actor=None, email=False, internal=False):
    users = users if users is not None else participants(req, internal)
    for user in users:
        if actor and actor.pk == user.pk:
            continue
        url = f'/requests/{req.pk}/'
        note = Notification.objects.create(user=user, request=req, text=text[:240], url=url)
        payload = {'text':text, 'url':url, 'reference':req.reference}
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
    if item.notification_id:
        user=item.notification.user
        if not user.is_active or user.company_id and not user.company.active:
            return 'skipped'
        if item.notification.request_id:
            from .permissions import visible_requests
            if not visible_requests(user).filter(pk=item.notification.request_id).exists():
                return 'skipped'
    payload=item.payload
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
        except Exception as exc:
            # Once a send has started, a connection error may mean the provider accepted it.
            # Surface this instead of creating duplicate approval messages.
            item.status='uncertain'
            item.error=type(exc).__name__[:100]
        item.save(update_fields=['status','error'])
        count+=1
    return count
