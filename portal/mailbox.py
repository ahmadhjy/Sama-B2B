import email
import imaplib
import re
from email.policy import default
from email.utils import parseaddr
from django.conf import settings
from django.db import transaction
from .models import MailReview, TravelRequest, User, WorkerState
from .permissions import visible_requests
from .workflow import add_message

def ingest_message(uid, raw):
    message=email.message_from_bytes(raw,policy=default)
    sender=parseaddr(message.get('From',''))[1].lower()
    subject=str(message.get('Subject',''))[:255]
    body_part=message.get_body(preferencelist=('plain',))
    body=body_part.get_content() if body_part else '(No plain-text body. Review the original email in IONOS.)'
    body=str(body)[:10000]
    reference=re.search(r'\bHS-\d{2}-[A-F0-9]{8}\b',subject.upper())
    req=TravelRequest.objects.filter(reference=reference.group(0)).first() if reference else None
    matches=User.objects.filter(email__iexact=sender,is_active=True)
    user=matches.first() if matches.count()==1 else None
    # Header From is forgeable. Without verified provider-specific authentication metadata,
    # quarantine even recognized replies for staff review, rather than impersonating a user.
    reason='Unrecognized request or sender'
    if req and user and visible_requests(user).filter(pk=req.pk).exists():
        reason='Recognized participant; review sender authenticity before adding to the conversation'
    MailReview.objects.get_or_create(uid=uid,defaults={'sender':sender,'subject':subject,'body':body,'reason':reason})

def fetch_mail():
    if not settings.IMAP_ENABLED or not settings.EMAIL_HOST_PASSWORD:
        return 0
    client=imaplib.IMAP4_SSL(settings.IMAP_HOST,settings.IMAP_PORT,timeout=25)
    try:
        client.login(settings.EMAIL_HOST_USER,settings.EMAIL_HOST_PASSWORD)
        client.select('INBOX',readonly=True)
        validity=client.response('UIDVALIDITY')[1][0].decode()
        state,_=WorkerState.objects.get_or_create(name='imap')
        _,result=client.uid('search',None,'ALL')
        uids=[int(x) for x in (result[0] or b'').split()]
        if state.value.get('validity')!=validity:
            state.value={'validity':validity,'last_uid':max(uids,default=0)};state.save()
            return 0
        count=0
        for uid in [x for x in uids if x>state.value.get('last_uid',0)][:20]:
            _,response=client.uid('fetch',str(uid),'(RFC822.SIZE)')
            size_line=b' '.join(x for x in response if isinstance(x,bytes))
            match=re.search(rb'RFC822.SIZE (\d+)',size_line)
            if match and int(match.group(1))>15*1024*1024:
                MailReview.objects.get_or_create(uid=f'{validity}:{uid}',defaults={'sender':'','subject':'Oversized incoming email','reason':'Review in IONOS; message exceeds 15 MB'})
            else:
                _,parts=client.uid('fetch',str(uid),'(BODY.PEEK[])')
                raw=next((part[1] for part in parts if isinstance(part,tuple)),b'')
                if raw: ingest_message(f'{validity}:{uid}',raw)
            state.value['last_uid']=uid;state.save(); count+=1
        return count
    finally:
        try: client.logout()
        except Exception: pass

@transaction.atomic
def accept_mail(actor, item, req):
    if item.resolved:
        return
    from .permissions import is_ceo, can_work
    if not is_ceo(actor) and not can_work(actor,req):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied()
    add_message(actor,req.pk,f'Email received from {item.sender} (reviewed by {actor.label}):\n\n{item.body}',token=f'mail:{item.pk}')
    item.resolved=True;item.save()
