import base64
import json
import uuid
from datetime import timedelta
from io import BytesIO
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_POST, require_GET
from . import workflow
from .accounting import AccountingUnavailable, bridge_call, sync_companies
from .ai import AssistantUnavailable, generate
from .auth import allow_attempt
from .fields import cipher
from .files import save_attachment, read_upload
from .forms import LoginForm, ProfileForm, TeamForm, RequestForm, QuoteForm
from .models import (User, Company, TravelRequest, Quote, Approval, Attachment, Draft, Audit, Message,
    Notification, Delivery, AIBudget, AICall, WorkerState, PushSubscription, MailReview)
from .notifications import safe_push_endpoint
from .permissions import (is_ceo, can_create, can_finance, can_work, can_submit_quote, can_view_passport, can_attachment, visible_requests)

def flash_error(request, exc):
    messages.error(request,' '.join(exc.messages) if isinstance(exc,ValidationError) else str(exc))

@sensitive_post_parameters('password')
def sign_in(request):
    if request.user.is_authenticated: return redirect('dashboard')
    form=LoginForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        username=form.cleaned_data['username']
        permitted=allow_attempt('login:'+username.lower(),15) and allow_attempt('ip:'+request.META.get('REMOTE_ADDR',''),100)
        if not permitted:
            form.add_error(None,'Too many login attempts. Please wait 15 minutes before trying again.')
        else:
            try:
                user=authenticate(request,**form.cleaned_data)
                if user:
                    login(request,user)
                    Audit.objects.create(actor=user,action='login',target=user.username)
                    return redirect('dashboard')
                form.add_error(None,'The account number or user ID and password do not match.')
            except AccountingUnavailable as exc:
                form.add_error(None,str(exc))
    return render(request,'portal/login.html',{'form':form})

@require_POST
def sign_out(request):
    logout(request)
    return redirect('login')

@login_required
def dashboard(request):
    qs=visible_requests(request.user)
    counts=dict(qs.values_list('status').annotate(total=Count('pk',distinct=True)))
    recent=list(qs[:6])
    approvals=Approval.objects.filter(user=request.user,decision='pending',quote__superseded=False,quote__valid_until__gt=timezone.now(),quote__request__status='awaiting_approval').select_related('quote__request')
    context={'recent':recent,'total':qs.count(),'active_count':qs.exclude(status__in=['closed','cancelled']).count(),
             'confirmed_count':qs.filter(status__in=['confirmed','closed']).count(),'approval_count':approvals.count(),
             'approvals':approvals[:4], 'counts':counts,'page_title':'Overview'}
    if request.user.is_sama and request.user.role in ('sales','ceo'):
        context['queue_count']=TravelRequest.objects.filter(assignee__isnull=True,status='pending').count()
    return render(request,'portal/dashboard.html',context)

@login_required
def requests_list(request):
    qs=visible_requests(request.user)
    if request.GET.get('status'):
        qs=qs.filter(status=request.GET['status'])
    if request.GET.get('q'):
        query=request.GET['q'][:100]; qs=qs.filter(Q(reference__icontains=query)|Q(title__icontains=query)|Q(destination__icontains=query))
    return render(request,'portal/requests.html',{'page_title':'Requests','page':Paginator(qs,25).get_page(request.GET.get('page')),'statuses':TravelRequest.Status.choices})

@login_required
def queue(request):
    if not request.user.is_sama or request.user.role not in ('ceo','sales'): raise PermissionDenied()
    qs=TravelRequest.objects.filter(assignee__isnull=True,status='pending').select_related('company').order_by('created_at')
    return render(request,'portal/queue.html',{'page_title':'Request queue','page':Paginator(qs,25).get_page(request.GET.get('page'))})

@login_required
@require_POST
def claim(request,req_id):
    try:
        req=workflow.claim_request(request.user,req_id)
        return redirect('request_detail',req_id=req.pk)
    except ValidationError as exc: flash_error(request,exc)
    return redirect('queue')

@login_required
def new_request(request):
    if not can_create(request.user): raise PermissionDenied()
    draft_id=request.GET.get('draft') or request.POST.get('draft_id')
    if draft_id:
        draft=get_object_or_404(Draft,pk=draft_id,user=request.user)
    else:
        draft=Draft.objects.filter(user=request.user,travelrequest__isnull=True).order_by('-updated_at').first()
        draft=draft or Draft.objects.create(user=request.user)
    form=RequestForm(request.POST or None,initial=draft.summary)
    if request.method=='POST' and form.is_valid():
        try:
            req=workflow.submit_request(request.user,draft.pk,form.cleaned_data)
            return redirect('request_detail',req_id=req.pk)
        except ValidationError as exc: flash_error(request,exc)
    return render(request,'portal/new_request.html',{'page_title':'Plan a trip','draft':draft,'form':form,'chat':draft.messages,
        'assistant_available':settings.AI_ENABLED and bool(settings.OPENAI_API_KEY),'summary_open':bool(draft.summary) or request.method=='POST'})

@login_required
@require_POST
def assistant(request,draft_id):
    if not can_create(request.user): raise PermissionDenied()
    if not allow_attempt(f'ai:{request.user.pk}',30,3600):
        return JsonResponse({'error':'Please wait before starting another assistant message.'},status=429)
    try:
        data=json.loads(request.body)
        if not isinstance(data,dict): raise ValueError()
    except (ValueError,UnicodeDecodeError):
        return JsonResponse({'error':'Invalid message.'},status=400)
    summary=data.get('action')=='summary'
    content=str(data.get('message','')).strip()
    if not summary and not 1<=len(content)<=3000:
        return JsonResponse({'error':'Enter a message of up to 3,000 characters.'},status=400)
    with transaction.atomic():
        draft=get_object_or_404(Draft.objects.select_for_update(),pk=draft_id,user=request.user)
        if TravelRequest.objects.filter(source_draft=draft).exists(): return JsonResponse({'error':'This request has already been submitted.'},status=409)
        if draft.ai_busy_until and draft.ai_busy_until>timezone.now(): return JsonResponse({'error':'Please wait for the current reply.'},status=409)
        if len(draft.messages)>=40: return JsonResponse({'error':'Please generate or edit your request summary now.'},status=400)
        if not summary: draft.messages.append({'role':'user','content':content})
        draft.ai_busy_until=timezone.now()+timedelta(seconds=110);draft.save()
        conversation=list(draft.messages)
    try:
        answer=generate(request.user,conversation,summary=summary)
        with transaction.atomic():
            draft=Draft.objects.select_for_update().get(pk=draft.pk)
            if summary: draft.summary=answer
            else: draft.messages.append(answer)
            draft.ai_busy_until=None;draft.save()
        return JsonResponse({'summary':answer} if summary else {'message':answer})
    except AssistantUnavailable as exc:
        Draft.objects.filter(pk=draft.pk).update(ai_busy_until=None)
        return JsonResponse({'error':str(exc)},status=503)

@login_required
def request_detail(request,req_id):
    req=get_object_or_404(visible_requests(request.user),pk=req_id)
    work=can_work(request.user,req); submit=can_submit_quote(request.user,req)
    thread=req.messages.select_related('author').prefetch_related('attachments').all()
    if not work: thread=thread.filter(internal=False)
    for item in thread:
        item.visible_files=[a for a in item.attachments.all() if can_attachment(request.user,a)]
    quotes=list(req.quotes.prefetch_related('approvals__user'))
    quote=next((q for q in quotes if not q.superseded),None)
    decision=quote.approvals.filter(user=request.user).first() if quote else None
    approvers=User.objects.filter(company=req.company,is_active=True,can_approve=True)
    if not settings.ALLOW_SELF_APPROVAL: approvers=approvers.exclude(pk=req.requester_id)
    sensitive=can_view_passport(request.user,req.requester,req)
    profile=req.requester if sensitive else None
    current=request.user
    steps=[('pending','Submitted'),('in_progress','With Sama'),('quote_sent','Quotation'),('awaiting_approval','Approvals'),('booking','Booking'),('confirmed','Confirmed')]
    index={'pending':0,'in_progress':1,'awaiting_client':1,'quote_sent':2,'awaiting_approval':3,'approved':3,'booking':4,'confirmed':5,'closed':5}.get(req.status,-1)
    return render(request,'portal/request_detail.html',{'page_title':req.reference,'req':req,'thread':thread,'quote':quote,
        'quotes':quotes,'decision':decision,'can_work':work,'can_submit':submit,'can_decide':bool(decision and decision.decision=='pending' and current.can_approve and quote and not quote.expired and req.status=='awaiting_approval'),
        'approvers':approvers,'profile':profile,'private_travellers':req.traveller_details if sensitive else '',
        'steps':[{'label':label,'done':i<index,'current':i==index} for i,(_,label) in enumerate(steps)],
        'last_message_id': max([m.pk for m in thread],default=0),
        'message_token':uuid.uuid4().hex,'sales_users':User.objects.filter(company__isnull=True,is_active=True,role__in=['ceo','sales']) if is_ceo(current) else [],
        'can_cancel':submit and req.status not in ('booking','confirmed','closed','cancelled')})

@login_required
@require_POST
def request_message(request,req_id):
    get_object_or_404(visible_requests(request.user),pk=req_id)
    try:
        workflow.add_message(request.user,req_id,request.POST.get('body',''),request.FILES.getlist('attachments'),
            internal=request.POST.get('internal')=='on',sensitive=request.POST.get('sensitive')=='on',token=request.POST.get('token','')[:64])
    except ValidationError as exc: flash_error(request,exc)
    return redirect('request_detail',req_id=req_id)

@login_required
@require_POST
def status_change(request,req_id):
    get_object_or_404(visible_requests(request.user),pk=req_id)
    try:
        if request.POST.get('action')=='reassign':
            member=get_object_or_404(User,pk=request.POST.get('assignee'))
            workflow.reassign_request(request.user,req_id,member,request.POST.get('note','')[:2000])
        else:
            workflow.change_status(request.user,req_id,request.POST.get('status'),request.POST.get('note','')[:2000],request.POST.get('booking_reference',''))
    except ValidationError as exc: flash_error(request,exc)
    return redirect('request_detail',req_id=req_id)

@login_required
def quote_create(request,req_id):
    req=get_object_or_404(visible_requests(request.user),pk=req_id)
    if not can_work(request.user,req): raise PermissionDenied()
    latest=req.quotes.first()
    initial={'currency':'USD','payment_terms':'Payment terms to be agreed before booking.','valid_until':timezone.now()+timedelta(days=3)}
    if latest:
        initial.update({k:getattr(latest,k) for k in ('amount','currency','details','inclusions','exclusions','payment_terms')})
    form=QuoteForm(request.POST or None,initial=initial)
    if request.method=='POST' and form.is_valid():
        try:
            workflow.issue_quote(request.user,req.pk,form.cleaned_data)
            return redirect('request_detail',req_id=req.pk)
        except ValidationError as exc: form.add_error(None,exc)
    return render(request,'portal/form.html',{'page_title':'Prepare quotation','form':form,'heading':'A clear offer, ready for approval.',
        'description':f'{req.reference} · {req.company.name}. A revision replaces the previous offer and requires fresh approvals.','button':'Send quotation','back':reverse('request_detail',args=[req.pk])})

@login_required
@require_POST
def quote_approval(request,req_id,quote_id):
    get_object_or_404(visible_requests(request.user),pk=req_id)
    get_object_or_404(Quote,pk=quote_id,request_id=req_id,superseded=False)
    try:
        action=request.POST.get('action')
        if action=='submit': workflow.request_approval(request.user,req_id,quote_id)
        else: workflow.decide(request.user,req_id,quote_id,action,request.POST.get('comment',''))
    except ValidationError as exc: flash_error(request,exc)
    return redirect('request_detail',req_id=req_id)

@login_required
def quote_download(request,req_id,quote_id):
    get_object_or_404(visible_requests(request.user),pk=req_id)
    quote=get_object_or_404(Quote,pk=quote_id,request_id=req_id)
    from .pdf import quote_pdf
    return FileResponse(quote_pdf(quote),as_attachment=True,filename=quote.reference+'.pdf',content_type='application/pdf')

@login_required
def attachment_download(request,file_id):
    attachment=get_object_or_404(Attachment.objects.select_related('request','passport_owner'),pk=file_id)
    if not can_attachment(request.user,attachment): raise Http404()
    try:
        with attachment.file.open('rb') as stream: data=cipher().decrypt(stream.read())
    except (FileNotFoundError,OSError): raise Http404()
    Audit.objects.create(actor=request.user,action='file_download',target=str(attachment.pk))
    return FileResponse(BytesIO(data),as_attachment=True,filename=attachment.name,content_type=attachment.content_type)

@login_required
def profile(request):
    form=ProfileForm(request.POST or None,request.FILES or None,instance=request.user)
    if request.method=='POST' and form.is_valid():
        try:
            upload=request.FILES.get('passport_copy')
            if upload: read_upload(upload)
            with transaction.atomic():
                form.save()
                if upload: save_attachment(upload,request.user,passport_owner=request.user)
                Audit.objects.create(actor=request.user,action='profile_updated',target=request.user.username)
            messages.success(request,'Your profile is complete and saved.')
            return redirect('dashboard')
        except ValidationError as exc: form.add_error('passport_copy',exc)
    return render(request,'portal/profile.html',{'page_title':'Your profile','form':form,'completion':not request.user.profile_complete,'passport_files':request.user.passport_files.all()})

@login_required
@sensitive_post_parameters('old_password','new_password1','new_password2')
def password_change(request):
    if request.user.is_primary:
        messages.info(request,'Your company password is managed in Sama Accounting. Contact Sama to reset it.');return redirect('profile')
    form=PasswordChangeForm(request.user,request.POST or None)
    if request.method=='POST' and form.is_valid():
        user=form.save();update_session_auth_hash(request,user);messages.success(request,'Password updated.');return redirect('profile')
    return render(request,'portal/form.html',{'page_title':'Change password','heading':'Keep your account secure.','form':form,'button':'Update password'})

@login_required
def team(request):
    if is_ceo(request.user):
        members=User.objects.select_related('company').all().order_by('company__name','first_name')
    elif request.user.role=='owner': members=User.objects.filter(company=request.user.company).order_by('first_name')
    else: raise PermissionDenied()
    return render(request,'portal/team.html',{'page_title':'People & access','members':members})

@login_required
@sensitive_post_parameters('password')
def team_edit(request,user_id=None):
    actor=request.user
    if not (is_ceo(actor) or actor.role=='owner'): raise PermissionDenied()
    qs=User.objects.all() if is_ceo(actor) else User.objects.filter(company=actor.company)
    member=get_object_or_404(qs,pk=user_id) if user_id else User(company=actor.company if not actor.is_sama else None)
    form=TeamForm(request.POST or None,request.FILES or None,instance=member,actor=actor)
    if request.method=='POST' and form.is_valid():
        try:
            upload=request.FILES.get('passport_copy')
            if upload: read_upload(upload)
            with transaction.atomic():
                if member.pk:
                    original=User.objects.select_for_update().get(pk=member.pk)
                    changed_approval=(original.can_approve and not form.cleaned_data.get('can_approve',original.can_approve)) or (original.is_active and not form.cleaned_data.get('is_active',original.is_active))
                    pending=Approval.objects.filter(user=original,decision='pending',quote__superseded=False,quote__request__status='awaiting_approval').exists()
                    if changed_approval and pending:
                        raise ValidationError('This user has pending approvals. Ask Sama to revise or cancel those quotations before removing their approval access.')
                saved=form.save(commit=False)
                if not saved.pk:
                    prefix=actor.company.account_number if actor.company_id else 'SAMA'
                    saved.username=prefix+'-'+uuid.uuid4().hex[:6].upper()
                if form.cleaned_data.get('password'): saved.set_password(form.cleaned_data['password'])
                saved.save()
                if upload: save_attachment(upload,actor,passport_owner=saved)
                Audit.objects.create(actor=actor,action='user_access_updated',target=saved.username,detail=f'Role: {saved.role}; approver: {saved.can_approve}; active: {saved.is_active}')
            messages.success(request,f'User saved. Login ID: {saved.username}')
            return redirect('team')
        except ValidationError as exc: form.add_error(None,exc)
    return render(request,'portal/form.html',{'page_title':'Edit user' if user_id else 'Add user','heading':member.label if user_id else 'Give your team the right access.',
        'description':'First name, last name and an initial password are required. The user completes missing profile information at first login. Approval permission is independent of role.',
        'form':form,'button':'Save user','back':reverse('team')})

@login_required
def notification_list(request):
    return render(request,'portal/notifications.html',{'page_title':'Notifications','notes':request.user.notifications.all()[:100]})

@login_required
@require_POST
def read_notifications(request):
    request.user.notifications.filter(read_at__isnull=True).update(read_at=timezone.now())
    return redirect('notifications')

@login_required
def notification_count(request):
    return JsonResponse({'unread':request.user.notifications.filter(read_at__isnull=True).count()})

@login_required
def request_updates(request,req_id):
    req=get_object_or_404(visible_requests(request.user),pk=req_id)
    items=req.messages.all()
    if not can_work(request.user,req): items=items.filter(internal=False)
    last=items.order_by('-id').values_list('id',flat=True).first() or 0
    return JsonResponse({'last_message_id':last,'status':req.status})

@login_required
def push_config(request):
    return JsonResponse({'public_key':settings.VAPID_PUBLIC_KEY})

@login_required
@require_POST
def push_subscribe(request):
    try:
        data=json.loads(request.body); endpoint=data['endpoint']; keys=data['keys']
        if not isinstance(endpoint,str) or not safe_push_endpoint(endpoint) or len(endpoint)>2048: raise ValueError()
        if not all(isinstance(keys[k],str) and 8<len(keys[k])<256 for k in ('p256dh','auth')): raise ValueError()
    except (ValueError,KeyError,TypeError): return JsonResponse({'error':'Invalid push subscription.'},status=400)
    existing=PushSubscription.objects.filter(endpoint=endpoint).first()
    if existing and existing.user_id!=request.user.pk:
        existing.delete()
    PushSubscription.objects.update_or_create(endpoint=endpoint,defaults={'user':request.user,'subscription':{'endpoint':endpoint,'keys':keys}})
    return JsonResponse({'ok':True})

@login_required
@require_POST
def push_unsubscribe(request):
    try: endpoint=json.loads(request.body).get('endpoint','')
    except ValueError: return JsonResponse({'error':'Invalid request.'},status=400)
    PushSubscription.objects.filter(user=request.user,endpoint=endpoint).delete()
    return JsonResponse({'ok':True})

@login_required
def finance(request):
    if not can_finance(request.user): raise PermissionDenied()
    companies=Company.objects.filter(active=True) if request.user.is_sama else Company.objects.filter(pk=request.user.company_id)
    selected=request.GET.get('company')
    company=get_object_or_404(companies,pk=selected) if selected else companies.first()
    kind=request.GET.get('kind','statement')
    if kind not in ('statement','invoices','invoice','receipts','receipt'): raise Http404()
    data=None; error=''
    if company:
        try:
            data=bridge_call('finance',{'company_id':str(company.erp_id),'kind':kind,'id':request.GET.get('id')})
            if not data: raise AccountingUnavailable('The accounting connection rejected this request.')
        except AccountingUnavailable as exc: error=str(exc)
    if data and request.GET.get('download')=='pdf':
        from .pdf import document
        if kind=='statement':
            rows=[[r.get('date',''),r.get('ref',''),r.get('type',''),r.get('debit',''),r.get('credit','')] for r in data['rows']]
            output=document('STATEMENT OF ACCOUNT',company.name,[('Balance',f"{data['closing']} USD")],rows,['Date','Reference','Type','Debit USD','Credit USD'])
        elif kind=='invoice':
            rows=[[r.get('date',''),r.get('service',''),r.get('destination',''),r.get('qty',''),r.get('amount','')] for r in data['lines']]
            output=document('INVOICE',f"{data['number']} | {company.name}",[('Totals',f"Total {data['total']} USD | Paid {data['paid']} USD | Remaining {data['remaining']} USD")],rows,['Date','Service','Destination','Qty',data['currency']])
        elif kind=='receipt':
            output=document('RECEIPT',f"{data['number']} | {company.name}",[('Payment',f"{data['kind']}\n{data['date']}\n{data['amount']} {data['currency']}")])
        else: raise Http404()
        return FileResponse(output,as_attachment=True,filename=f'HelloSama-{kind}.pdf',content_type='application/pdf')
    return render(request,'portal/finance.html',{'page_title':'Accounting','companies':companies,'selected_company':company,'kind':kind,'data':data,'error':error})

@login_required
def financial_attachment(request):
    if not can_finance(request.user): raise PermissionDenied()
    companies=Company.objects.filter(active=True) if request.user.is_sama else Company.objects.filter(pk=request.user.company_id)
    company=get_object_or_404(companies,pk=request.GET.get('company'))
    try:
        data=bridge_call('file',{'company_id':str(company.erp_id),'kind':request.GET.get('kind'),'id':request.GET.get('id'),'attachment_id':request.GET.get('attachment')})
        if not data or data.get('error'): raise AccountingUnavailable((data or {}).get('error','File unavailable.'))
        return FileResponse(BytesIO(base64.b64decode(data['content'])),as_attachment=True,filename=data['name'],content_type='application/octet-stream')
    except AccountingUnavailable as exc:
        messages.error(request,str(exc));return redirect('finance')

@login_required
def operations(request):
    if not is_ceo(request.user): raise PermissionDenied()
    if request.method=='POST':
        if request.POST.get('action')=='sync':
            try: messages.success(request,f'Synchronized {sync_companies()} companies.')
            except AccountingUnavailable as exc: flash_error(request,exc)
        elif request.POST.get('action')=='retry':
            delivery=get_object_or_404(Delivery,pk=request.POST.get('delivery'))
            if delivery.status in ('disabled','uncertain','failed'):
                Audit.objects.create(actor=request.user,action='delivery_retry',target=str(delivery.pk),detail='Administrator checked provider records before retrying.')
                delivery.status='pending';delivery.available_at=timezone.now();delivery.save()
        return redirect('operations')
    return render(request,'portal/operations.html',{'page_title':'Operations','companies':Company.objects.all(),
        'budget':AIBudget.objects.filter(month=timezone.now().strftime('%Y-%m')).first(),'budget_limit':settings.AI_MONTHLY_LIMIT_USD,
        'states':WorkerState.objects.all(),'deliveries':Delivery.objects.exclude(status__in=['sent','skipped']).order_by('-created_at')[:40],
        'audit':Audit.objects.select_related('actor').order_by('-created_at')[:30],'connections':{
        'Accounting':settings.ACCOUNTING_ENABLED,'AI assistant':settings.AI_ENABLED and bool(settings.OPENAI_API_KEY),
        'Email sending':settings.EMAIL_ENABLED and bool(settings.EMAIL_HOST_PASSWORD),'Incoming email':settings.IMAP_ENABLED,
        'Push notifications':bool(settings.VAPID_PRIVATE_KEY),'SMS (postponed)':False}})

@login_required
def mail_review(request):
    if not is_ceo(request.user): raise PermissionDenied()
    if request.method=='POST':
        item=get_object_or_404(MailReview,pk=request.POST.get('mail'))
        if request.POST.get('action')=='dismiss': item.resolved=True;item.save()
        else:
            req=TravelRequest.objects.filter(reference=request.POST.get('reference','').strip().upper()).first()
            if not req: messages.error(request,'Enter a valid request reference.')
            else:
                from .mailbox import accept_mail
                try: accept_mail(request.user,item,req);messages.success(request,'Email added to the conversation with its sender and reviewer identified.')
                except ValidationError as exc:flash_error(request,exc)
        return redirect('mail_review')
    return render(request,'portal/mail_review.html',{'page_title':'Incoming email','items':MailReview.objects.filter(resolved=False).order_by('-created_at')[:40]})

@require_GET
def health(request):
    return JsonResponse({'status':'ok','application':'HelloSama'})

@require_GET
def manifest(request):
    return JsonResponse({'name':'HelloSama Corporate Portal | Sama Tours','short_name':'HelloSama','start_url':'/','scope':'/',
        'display':'standalone','background_color':'#ffffff','theme_color':'#163e64',
        'icons':[{'src':'/static/brand/icon.svg','sizes':'any','type':'image/svg+xml','purpose':'any'}]},content_type='application/manifest+json')

@require_GET
def service_worker(request):
    return HttpResponse((settings.BASE_DIR/'static/service-worker.js').read_text(),content_type='application/javascript',headers={'Cache-Control':'no-cache','Service-Worker-Allowed':'/'})
