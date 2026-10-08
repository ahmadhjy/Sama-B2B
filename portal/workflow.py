import uuid
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from . import notifications
from .files import save_attachment, read_upload
from .models import Approval, Audit, Draft, Message, Quote, TravelRequest, User
from .permissions import can_create, can_work, can_submit_quote, is_ceo, visible_requests
from .chat import preference_text, itinerary_changed

def event(req, text, actor=None, **metadata):
    msg=Message.objects.create(request=req,kind='system',body=text,author=actor,metadata=metadata)
    Audit.objects.create(actor=actor,action='request_event',target=req.reference,detail=text)
    req.save(update_fields=['updated_at'])
    return msg

def locked(req_id):
    return TravelRequest.objects.select_for_update(of=('self',)).select_related('company','requester','assignee').get(pk=req_id)

@transaction.atomic
def submit_request(user, draft_id, data):
    if not can_create(user) or not user.profile_complete:
        raise PermissionDenied()
    draft=Draft.objects.select_for_update().get(pk=draft_id,user=user)
    previous=TravelRequest.objects.filter(source_draft=draft).first()
    if previous:
        return previous
    if draft.archived or draft.ai_busy_until and draft.ai_busy_until>timezone.now():
        raise ValidationError('This draft is closed or the assistant is still replying. Reopen it or wait before submitting.')
    data=dict(data)
    if draft.summary.get('selections') and itinerary_changed(draft.summary,data):
        raise ValidationError('Route, dates or passengers changed. Save your revised trip details, then choose options for the updated trip before submitting.')
    preferences=preference_text(draft.summary.get('selections',{}))
    if preferences:
        data['requirements']=(data.get('requirements','')+'\n\nSelected travel preferences (Sama to verify):\n'+preferences).strip()
    req=TravelRequest.objects.create(company=user.company,requester=user,source_draft=draft,
        reference='HS-'+timezone.localdate().strftime('%y')+'-'+uuid.uuid4().hex[:8].upper(),**data)
    for entry in draft.messages:
        Message.objects.create(request=req,author=user if entry['role']=='user' else None,
            kind='human' if entry['role']=='user' else 'ai',body=entry['content'],
            metadata={'sources':entry.get('sources',[]),'options':entry.get('options',[])})
    msg=event(req,f'{user.label} submitted this request. It is waiting for a Sama salesperson.',user)
    notifications.business_notice(req,f'New travel request {req.reference} is waiting in the queue.',f'event:{msg.pk}',url='/queue/')
    staff=User.objects.filter(company__isnull=True,role__in=['ceo','sales'],is_active=True)
    for member in staff:
        from .models import Notification, Delivery
        from django.conf import settings
        note=Notification.objects.create(user=member,text=f'New request {req.reference} is waiting in the queue.',url='/queue/')
        if settings.VAPID_PRIVATE_KEY:
            Delivery.objects.get_or_create(dedupe_key=f'queue:{req.pk}:push:{member.pk}',defaults={
                'notification':note,'channel':'push','recipient':str(member.pk),
                'payload':{'text':'A new request is waiting in the queue.','url':'/queue/','reference':req.reference}})
    return req

@transaction.atomic
def claim_request(user, req_id):
    if not is_ceo(user) and not (user.is_sama and user.role==User.Role.SALES):
        raise PermissionDenied()
    req=locked(req_id)
    if req.assignee_id or req.status != TravelRequest.Status.PENDING:
        raise ValidationError('This request has already been taken over. Refresh the queue.')
    req.assignee=user; req.status=TravelRequest.Status.PROGRESS; req.save()
    msg=event(req,f'{user.label} took over this request.',user)
    notifications.notify(req,f'{user.label} is now handling {req.reference}.',f'event:{msg.pk}',actor=user)
    return req

@transaction.atomic
def reassign_request(user, req_id, assignee, reason):
    if not is_ceo(user):
        raise PermissionDenied()
    if not reason.strip() or not assignee.is_active or not assignee.is_sama or assignee.role not in ('sales','ceo'):
        raise ValidationError('Select an active Sama salesperson and enter a reason.')
    req=locked(req_id)
    old=req.assignee.label if req.assignee else 'Unassigned'
    req.assignee=assignee
    if req.status=='pending': req.status='in_progress'
    req.save()
    msg=event(req,f'Reassigned from {old} to {assignee.label}. Reason: {reason.strip()}',user)
    notifications.notify(req,f'{assignee.label} is now handling {req.reference}.',f'event:{msg.pk}',actor=user)

@transaction.atomic
def add_message(user, req_id, body, uploads=(), internal=False, sensitive=False, token=''):
    req=locked(req_id)
    if not visible_requests(user).filter(pk=req.pk).exists():
        raise PermissionDenied()
    if internal and not can_work(user,req):
        raise PermissionDenied()
    if sensitive and not (can_work(user,req) or can_submit_quote(user,req)):
        raise PermissionDenied()
    if req.status in ('closed','cancelled'):
        raise ValidationError('This request is closed. Create a new request to continue.')
    body=body.strip()
    if len(body)>10000 or (not body and not uploads):
        raise ValidationError('Enter a message or attach a file (message limit: 10,000 characters).')
    if len(uploads)>5:
        raise ValidationError('Attach at most five files per message.')
    for upload in uploads: read_upload(upload)
    if token and req.messages.filter(metadata__submission_token=token,author=user).exists():
        return
    msg=Message.objects.create(request=req,author=user,body=body or 'Shared an attachment.',internal=internal,
        metadata={'submission_token':token})
    for upload in uploads:
        save_attachment(upload,user,req=req,message=msg,internal=internal,sensitive=sensitive)
    req.save(update_fields=['updated_at'])
    notifications.notify(req,f'New {"internal note" if internal else "message"} in {req.reference}.',f'message:{msg.pk}',actor=user,internal=internal,email=True)

@transaction.atomic
def issue_quote(user, req_id, data):
    req=locked(req_id)
    if not can_work(user,req):
        raise PermissionDenied()
    if req.status in ('pending','booking','confirmed','closed','cancelled'):
        raise ValidationError('This request is not ready for a quotation.')
    if not req.requester.profile_complete:
        raise ValidationError('The requester must complete their profile before a quotation can be sent.')
    if data['valid_until']<=timezone.now():
        raise ValidationError('The quotation validity must be in the future.')
    latest=req.quotes.first()
    req.quotes.update(superseded=True)
    quote=Quote.objects.create(request=req,version=latest.version+1 if latest else 1,created_by=user,**data)
    req.status='quote_sent'; req.save()
    msg=event(req,f'{user.label} sent quotation {quote.reference}. Review it and submit it for approval.',user,quote_id=str(quote.pk))
    notifications.notify(req,f'Quotation {quote.reference} is ready to review.',f'event:{msg.pk}',actor=user,email=True)
    return quote

@transaction.atomic
def request_approval(user, req_id, quote_id):
    from django.conf import settings
    req=locked(req_id)
    if not can_submit_quote(user,req):
        raise PermissionDenied()
    quote=Quote.objects.get(pk=quote_id,request=req,superseded=False)
    if quote.expired:
        raise ValidationError('This quotation has expired. Ask Sama for a revised quotation.')
    if quote.submitted_at:
        return quote
    if req.status!='quote_sent':
        raise ValidationError('This quotation cannot be submitted in the current phase.')
    approvers=list(User.objects.select_for_update().filter(company=req.company,is_active=True,can_approve=True))
    if not settings.ALLOW_SELF_APPROVAL:
        approvers=[u for u in approvers if u.pk != req.requester_id]
    if not approvers:
        raise ValidationError('Your company administrator must assign at least one quotation approver.')
    if any(not u.email or not u.phone for u in approvers):
        raise ValidationError('Every approver must complete their email and mobile number before submission.')
    for approver in approvers:
        Approval.objects.create(quote=quote,user=approver,name_snapshot=approver.label)
    quote.submitted_at=timezone.now(); quote.approval_required_count=len(approvers); quote.save()
    req.status='awaiting_approval'; req.save()
    msg=event(req,f'{user.label} submitted {quote.reference} for approval by all {len(approvers)} approvers: '+', '.join(u.label for u in approvers)+'.',user)
    notifications.notify(req,f'Your approval is requested for {quote.reference}.',f'approval:{msg.pk}',users=approvers,email=True,approval_quote=quote)
    return quote

@transaction.atomic
def decide(user, req_id, quote_id, decision, comment=''):
    req=locked(req_id)
    if not user.can_approve or not user.is_active or user.company_id != req.company_id:
        raise PermissionDenied()
    quote=Quote.objects.get(pk=quote_id,request=req,superseded=False)
    approval=Approval.objects.select_for_update().filter(quote=quote,user=user).first()
    if not approval:
        raise PermissionDenied()
    if approval.decision != 'pending':
        raise ValidationError('Your decision has already been recorded.')
    if quote.expired or req.status!='awaiting_approval':
        raise ValidationError('This quotation is no longer awaiting approval.')
    if decision not in ('approved','rejected'):
        raise ValidationError('Choose Approve or Reject.')
    if decision=='rejected' and not comment.strip():
        raise ValidationError('Please explain what needs to change.')
    approval.decision=decision; approval.comment=comment[:2000]; approval.decided_at=timezone.now(); approval.save()
    approved=quote.approvals.filter(decision='approved').count()
    pending=', '.join(quote.approvals.filter(decision='pending').values_list('name_snapshot',flat=True))
    msg=event(req,f'{user.label} {decision} {quote.reference}. {approved} of {quote.approval_required_count} approvals received.'+(f' Waiting for {pending}.' if pending else ''),user)
    if comment:
        Message.objects.create(request=req,author=user,body=comment[:2000])
    if decision=='rejected':
        req.status='rejected'
    elif quote.all_approved:
        req.status='approved'
        event(req,'All required approvers accepted this quotation. Sama will now verify availability and arrange the booking.')
        notifications.business_notice(req,f'All approvals received for {quote.reference}. Ready for booking review.',f'approved:{quote.pk}')
    req.save()
    notifications.notify(req,f'{user.label} {decision} {quote.reference}.',f'event:{msg.pk}',actor=user,email=True)

@transaction.atomic
def change_status(user, req_id, status, note='', booking_reference=''):
    req=locked(req_id)
    if status=='cancelled' and can_submit_quote(user,req) and req.status not in ('booking','confirmed','closed','cancelled'):
        pass
    elif not can_work(user,req):
        raise PermissionDenied()
    transitions={'in_progress':{'awaiting_client','cancelled'},'awaiting_client':{'in_progress','cancelled'},
        'quote_sent':{'cancelled'},'awaiting_approval':{'cancelled'},'rejected':{'in_progress','cancelled'},
        'expired':{'in_progress','cancelled'},'approved':{'booking','cancelled'},'booking':{'confirmed','cancelled'},
        'confirmed':{'closed'},'pending':{'cancelled'}}
    if status not in transitions.get(req.status,set()):
        raise ValidationError('That status change is not available from the current phase.')
    if status in ('booking','confirmed'):
        quote=req.quotes.filter(superseded=False).first()
        if not quote or not quote.all_approved or (status=='booking' and quote.expired):
            raise ValidationError('A current quotation must have all required approvals before booking starts.')
    if status=='confirmed' and not booking_reference.strip():
        raise ValidationError('Enter the supplier booking reference before confirming.')
    if status=='cancelled' and not note.strip():
        raise ValidationError('Enter a cancellation reason.')
    req.status=status
    if booking_reference: req.booking_reference=booking_reference[:120]
    req.save()
    msg=event(req,f'Status changed to {req.get_status_display()}.'+(f' {note.strip()}' if note else ''),user)
    notifications.notify(req,f'{req.reference}: {req.get_status_display()}.',f'event:{msg.pk}',actor=user,email=True)

def expire_quotes():
    ids=list(Quote.objects.filter(superseded=False,valid_until__lte=timezone.now(),request__status__in=['quote_sent','awaiting_approval','approved']).values_list('request_id',flat=True))
    for req_id in ids:
        with transaction.atomic():
            req=locked(req_id)
            quote=req.quotes.filter(superseded=False).first()
            if quote and quote.expired and req.status in ['quote_sent','awaiting_approval','approved']:
                req.status='expired'; req.save()
                msg=event(req,f'Quotation {quote.reference} expired. A revised quotation is required.')
                notifications.notify(req,f'Quotation {quote.reference} has expired.',f'event:{msg.pk}')
