"""Client views use the same request visibility and workflow rules as the main portal."""
from datetime import timedelta
import uuid
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from . import workflow, notifications
from .auth import allow_attempt
from .forms import RequestForm
from .models import Audit, User, TravelRequest, Quote
from .permissions import visible_requests, can_work, can_submit_quote, can_attachment, is_ceo
from .pdf import document

def locked_visible_requests(user):
    # The visibility query can contain DISTINCT for approvers/requesters. PostgreSQL
    # cannot lock that query directly; lock only request rows selected by it.
    return TravelRequest.objects.filter(pk__in=visible_requests(user).values('pk')).select_related(
        'company','requester','assignee').select_for_update(of=('self',))

@login_required
def quick_approval(request,req_id,quote_id):
    req=get_object_or_404(visible_requests(request.user),pk=req_id)
    quote=get_object_or_404(Quote,pk=quote_id,request=req)
    decision=quote.approvals.filter(user=request.user).first()
    can_decide=bool(decision and decision.decision=='pending' and request.user.can_approve and
                    not quote.superseded and not quote.expired and req.status=='awaiting_approval')
    return render(request,'portal/quick_approval.html',{'page_title':'Review travel approval','req':req,'quote':quote,
        'decision':decision,'can_decide':can_decide})


@login_required
def request_export(request, req_id):
    req=get_object_or_404(visible_requests(request.user),pk=req_id)
    sections=[('Trip',f'{req.title}\n{req.origin} → {req.destination}\nDeparture: {req.departure}\nReturn: {req.return_date or "One way / flexible"}\nPassengers: {req.travellers}\nRequested by: {req.requester.label}'),
              ('Progress',req.get_status_display()),('Requirements',req.requirements or 'No additional preferences.')]
    full=request.GET.get('conversation')=='1'
    if full:
        thread=req.messages.select_related('author').prefetch_related('attachments')
        if not can_work(request.user,req): thread=thread.filter(internal=False)
        for message in thread:
            author=message.author.label if message.author else ('Assistant' if message.kind=='ai' else 'Update')
            heading=f'{timezone.localtime(message.created_at):%d %b %Y %H:%M} · {author}'
            if message.internal: heading+=' · Internal'
            files=[a.name for a in message.attachments.all() if can_attachment(request.user,a)]
            sections.append((heading,message.body + ('\nAttachments: '+', '.join(files) if files else '')))
        for quote in req.quotes.prefetch_related('approvals').all():
            decisions='\n'.join(f'{a.name_snapshot}: {a.get_decision_display()}' for a in quote.approvals.all())
            sections.append((quote.reference+(' (superseded)' if quote.superseded else ''),
                f'{quote.amount} {quote.currency}\n{quote.details}\n{quote.inclusions}\n{quote.exclusions}\n{quote.payment_terms}\nValid until {timezone.localtime(quote.valid_until):%d %b %Y %H:%M}\n{decisions}'))
    sections.append(('Documents','Download tickets, vouchers and authorized attachments from Files & documents in the portal. This export does not embed passport files.'))
    Audit.objects.create(actor=request.user,action='conversation_export' if full else 'request_export',target=req.reference)
    return FileResponse(document('CONVERSATION ARCHIVE' if full else 'TRAVEL REQUEST',req.reference,sections),
        as_attachment=True,filename=req.reference+('-conversation.pdf' if full else '-summary.pdf'),content_type='application/pdf')


@login_required
def request_edit(request,req_id):
    with transaction.atomic():
        req=get_object_or_404(locked_visible_requests(request.user),pk=req_id)
        if not can_submit_quote(request.user,req): raise PermissionDenied()
        if req.status not in ('pending','in_progress','awaiting_client') or req.quotes.exists():
            messages.info(request,'A quotation or booking already exists. Send Sama a message to request a revision.')
            return redirect('request_detail',req_id=req.pk)
        form=RequestForm(request.POST or None,instance=req)
        if request.method=='POST' and form.is_valid():
            form.save()
            msg=workflow.event(req,f'{request.user.label} updated the trip details. Sama will review the revised request.',request.user)
            notifications.notify(req,'Trip details updated for '+req.reference,f'event:{msg.pk}',actor=request.user,email=True)
            messages.success(request,'Trip details updated.')
            return redirect('request_detail',req_id=req.pk)
    return render(request,'portal/form.html',{'page_title':'Edit travel request','heading':'Update your trip details',
        'description':req.reference,'form':form,'button':'Save changes','back':reverse('request_detail',args=[req.pk])})


@login_required
@require_POST
def remind_approvers(request,req_id):
    with transaction.atomic():
        req=get_object_or_404(locked_visible_requests(request.user),pk=req_id)
        if not (can_submit_quote(request.user,req) or can_work(request.user,req)): raise PermissionDenied()
        quote=req.quotes.filter(superseded=False).first()
        if not quote or quote.expired or req.status!='awaiting_approval':
            messages.error(request,'There is no current quotation waiting for approval.')
        elif not allow_attempt('approval-reminder:'+str(req.pk),1,3600):
            messages.info(request,'A reminder was already requested within the last hour.')
        else:
            users=User.objects.filter(approval__quote=quote,approval__decision='pending',is_active=True,can_approve=True)
            msg=workflow.event(req,f'{request.user.label} requested a reminder for pending approvers.',request.user)
            notifications.notify(req,'Reminder: your approval is needed for '+req.reference,f'reminder:{msg.pk}',
                users=users,email=True,approval_quote=quote)
            messages.success(request,'Reminder added to the approvers’ notifications. Enabled delivery channels will be processed by the notification worker.')
    return redirect('request_detail',req_id=req_id)


@login_required
def travel_overview(request):
    if not (is_ceo(request.user) or request.user.role=='owner' and request.user.company_id): raise PermissionDenied()
    today=timezone.localdate()
    trips=visible_requests(request.user).filter(status__in=['confirmed','closed']).order_by('departure','reference')
    current=trips.filter(departure__lte=today,return_date__gte=today)
    upcoming=trips.filter(departure__gt=today,departure__lte=today+timedelta(days=7))
    unknown=trips.filter(departure__lte=today,return_date__isnull=True)
    counts={'current':current.count(),'upcoming':upcoming.count(),'unknown':unknown.count()}
    scope=request.GET.get('period','current')
    if scope=='current': trips=current
    elif scope=='upcoming': trips=upcoming
    elif scope=='unknown': trips=unknown
    elif scope!='all': trips=current
    query=request.GET.get('q','')[:100]
    if query: trips=trips.filter(Q(destination__icontains=query)|Q(reference__icontains=query)|Q(requester__first_name__icontains=query)|Q(requester__last_name__icontains=query))
    if request.GET.get('download')=='pdf':
        rows=[[r.requester.label,r.reference,r.destination,str(r.departure),str(r.return_date or 'Not recorded')] for r in trips]
        output=document('TRAVEL OVERVIEW',str(today),[('Source','Confirmed portal requests and recorded travel dates. This is not live location or flight-status tracking. The named person is the requester; additional passengers are not individually tracked.')],rows,['Requester','Reference','Destination','Departure','Return'])
        return FileResponse(output,as_attachment=True,filename='HelloSama-travel-overview.pdf',content_type='application/pdf')
    return render(request,'portal/travel_overview.html',{'page_title':'Travel overview','trips':trips,'counts':counts,'period':scope,'message_token':uuid.uuid4().hex})


@login_required
@require_POST
def travel_message(request):
    if not (is_ceo(request.user) or request.user.role=='owner' and request.user.company_id): raise PermissionDenied()
    ids=request.POST.getlist('trip')
    body=request.POST.get('body','').strip()
    if not 1<=len(ids)<=50 or not body or len(body)>2000:
        messages.error(request,'Choose 1–50 trips and enter a message of up to 2,000 characters.')
        return redirect('travel_overview')
    try:
        with transaction.atomic():
            trips=list(visible_requests(request.user).filter(pk__in=ids,status='confirmed').select_for_update(of=('self',)).order_by('pk'))
            if len(trips)!=len(set(ids)): raise PermissionDenied()
            token=request.POST.get('token','')[:64]
            for trip in trips:
                workflow.add_message(request.user,trip.pk,body,token=token)
        messages.success(request,f'Message added to {len(trips)} trip conversation(s).')
    except (ValueError,ValidationError):
        messages.error(request,'The selected trips changed. Refresh the travel overview and select active confirmed trips.')
    return redirect('travel_overview')
