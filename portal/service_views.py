import hashlib
import json
import logging
import uuid
from datetime import timedelta
from decimal import Decimal
from io import BytesIO

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST

from . import hotel_search, providers, service_credits as credits, service_forms as forms, service_suppliers as suppliers
from .auth import allow_attempt
from .models import Company, CreditEntry, ServiceOffer, ServiceOrder
from .permissions import is_ceo

SERVICES = {'hotel':'Hotels', 'esim':'eSIM', 'insurance':'Travel insurance'}
QUOTE_ERRORS = (providers.ProviderUnavailable, ValidationError, hotel_search.Clarification,
                ValueError, KeyError, TypeError, AttributeError, IndexError)


def customer(user):
    if not credits.allowed(user):
        raise PermissionDenied


def limit(user, action, maximum):
    if not allow_attempt(f'services:{action}:{user.pk}', maximum, 3600):
        raise ValidationError('Please wait before trying again.')


def error_text(exc):
    if isinstance(exc, ValidationError):
        return ' '.join(exc.messages)
    if isinstance(exc, hotel_search.Clarification):
        return exc.question
    return 'The provider could not complete this step. Please try again or contact Sama.'


def count_value(raw, maximum):
    try:
        return max(1,min(maximum,int(raw or 1)))
    except (ValueError,TypeError):
        return 1


def search_rows(kind, data):
    if kind == 'esim':
        query = {k:data[k] for k in ('bundle_category','region_code','sort_by','page')}
        query['page'] = query['page'] or 1
        query['sort_by'] = query['sort_by'] or 'price_asc'
        if query['bundle_category']!='region':
            query.pop('region_code',None)
        if data['destination'] and query['bundle_category']=='country':
            query['country_code'] = forms.iso3(data['destination'])
        rows,total = suppliers.esim_catalog(query)
        return rows, query, total
    if kind == 'insurance':
        query = dict(destination=forms.iso3(data['destination']), residence=forms.iso3(data['residence']),
                     start=str(data['start']),end=str(data['end']),births=[str(b) for b in data['births']])
        return suppliers.insurance_quotes(query),query,0
    cities = providers.hotel_cities(data['city'],data['destination'])
    exact = [c for c in cities if c['exact']]
    if len(exact)!=1:
        suggestions = ', '.join(c['name'] for c in cities[:5])
        raise ValidationError('Enter the exact hotel city.'+(f' Provider matches: {suggestions}.' if suggestions else ' No matching city was found.'))
    filters = hotel_search.merge({}, {'landmark':data['landmark'],'radius_km':float(data['radius']) if data['radius'] is not None else None,
        'hotel_name':data['hotel_name'],'stars':data['stars'],'board_basis':data['board'] or 'any',
        'refundability':data['refundability'] or 'any','sort':data['sort'] or 'price'})
    query = dict(start=str(data['start']),end=str(data['end']),rooms=data['rooms'])
    return providers.hotels(exact[0]['id'],data['nationality'],data['start'],data['end'],data['rooms'],
                            criteria=filters,checkout=True),query,0


def save_offers(user,kind,rows,query):
    offers=[]
    expiry = timezone.now()+timedelta(minutes=10)
    prepared = []
    for row in rows[:80]:
        sandbox = kind=='insurance' and providers.insurance_is_test()
        cost = credits.credits_for(row['price_min'],row['currency'],sandbox)
        record = ServiceOffer(company_id=user.company_id,actor=user,kind=kind,
            label=row['label'],price=Decimal(row['price_min']),currency=row['currency'],credits=cost,
            sandbox=sandbox,expires=expiry,payload=json.dumps({'row':row,'search':query}))
        prepared.append(record)
        offers.append(dict(offer=record,detail=row['detail'],attributes=row.get('attributes',[]),
            rooms=row.get('room_details',[]),stars=row.get('stars'), purchasable=cost is not None and suppliers.enabled(kind,sandbox)))
    ServiceOffer.objects.bulk_create(prepared)
    return offers


@login_required
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def catalog(request, kind):
    customer(request.user)
    if kind not in SERVICES:
        raise Http404
    count = count_value((request.POST if request.method=='POST' else request.GET).get('count'), 10 if kind=='hotel' else 20)
    form_class = {'hotel':forms.HotelSearch,'esim':forms.EsimSearch,'insurance':forms.InsuranceSearch}[kind]
    submitted = (request.method=='POST' and 'set_count' not in request.POST) or (kind=='esim' and request.GET.get('browse')=='1')
    data = request.POST if request.method=='POST' else request.GET if submitted else None
    connected = providers.available()[kind]
    region_choices=[]
    if kind=='esim' and connected:
        try:
            region_choices=suppliers.regions()
        except QUOTE_ERRORS:
            pass
    initial = request.POST if request.method=='POST' and not submitted else None
    form = form_class(data, initial=initial, **({'count':count} if kind!='esim' else {'regions':region_choices}))
    offers = []
    previous_page = next_page = None
    if submitted and connected and form.is_valid():
        try:
            limit(request.user,'search',60)
            if kind=='esim' and request.method=='POST':
                form.cleaned_data['page']=1
            rows, query, total = search_rows(kind,form.cleaned_data)
            offers = save_offers(request.user,kind,rows,query)
            if not offers:
                messages.info(request,'No matching offers were returned. Try changing the search.')
            if kind=='esim':
                page=query['page']
                from django.http import QueryDict
                params=QueryDict(mutable=True)
                for key in ('destination','bundle_category','region_code','sort_by'):
                    params[key]=form.cleaned_data[key]
                params['browse']='1'
                if page>1:
                    params['page']=page-1
                    previous_page=params.urlencode()
                if total>page*50 and page<200:
                    params['page']=page+1
                    next_page=params.urlencode()
        except QUOTE_ERRORS as exc:
            form.add_error(None,error_text(exc))
    groups = []
    if kind=='hotel':
        groups=[(f'Room {i+1}',[form[f'adults_{i}'],form[f'ages_{i}']]) for i in range(count)]
    elif kind=='insurance':
        groups=[(f'Traveller {i+1}',[form[f'birth_{i}']]) for i in range(count)]
    return render(request,'portal/service_catalog.html',dict(page_title=SERVICES[kind],kind=kind,
        form=form,groups=groups,offers=offers,connected=connected,count=count,counts=range(1,11 if kind=='hotel' else 21),
        previous_page=previous_page,next_page=next_page,
        balance=credits.wallet_balance(request.user.company_id),sandbox=kind=='insurance' and providers.insurance_is_test()))


def checked_price(offer, value, currency):
    if providers.amount(value) != str(offer.price) or currency != offer.currency or (
            credits.credits_for(offer.price,offer.currency,offer.sandbox) != offer.credits):
        raise ValidationError('The supplier price or exchange rate changed. Search again for a new quote.')


def hotel_disclosures(current):
    return {key:current.get(key) for key in ('termsAndConditions','cancellationPolicy','cancellationPolicies',
        'taxes','remarks','offerConfiguration','bookingOptions','extraServices') if current.get(key)}


def display_disclosures(data):
    policy=data.get('cancellationPolicy') or {}
    terms=[{'text':str(t.get('text') or ''),'url': t.get('url') if str(t.get('url')).startswith('https://') else ''}
           for t in data.get('termsAndConditions',[]) or [] if isinstance(t,dict)]
    return {'terms':terms,'cancellation':policy.get('policies',[]),
            'taxes':data.get('taxes'),'remarks':data.get('remarks')}


def disclosure_signature(offer, data):
    digest = hashlib.sha256(json.dumps(hotel_disclosures(data),sort_keys=True).encode()).hexdigest()
    return {'offer':str(offer.pk),'terms':digest}


@login_required
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def checkout(request, offer_id):
    customer(request.user)
    offer = get_object_or_404(ServiceOffer,pk=offer_id,company_id=request.user.company_id,actor=request.user)
    existing = ServiceOrder.objects.filter(offer=offer).first()
    if existing:
        return redirect('service_order',order_id=existing.pk)
    if offer.expires<=timezone.now() or offer.credits is None or not suppliers.enabled(offer.kind,offer.sandbox):
        messages.error(request,'This quote expired or checkout is not available. Search again.')
        return redirect('service_catalog',kind=offer.kind)
    if offer.kind=='insurance' and offer.sandbox!=providers.insurance_is_test():
        messages.error(request,'The insurance environment changed. Search again.')
        return redirect('service_catalog',kind=offer.kind)
    disclosures, review_token = {}, ''
    try:
        saved = json.loads(offer.payload)
        search = saved['search']
        rooms = [dict(adults=r['adults'],ages=r['childrenAges']) for r in search.get('rooms',[])]
        current = None
        if offer.kind=='hotel':
            limit(request.user,'prebook',45)
            price,currency,current = suppliers.prepare(offer,saved)
            checked_price(offer,price,currency)
            disclosures = display_disclosures(current)
            fingerprint = disclosure_signature(offer,current)
            review_token = signing.dumps(fingerprint,salt='hotel-checkout-terms')
            if request.method=='POST':
                try:
                    reviewed = signing.loads(request.POST.get('review_token',''),salt='hotel-checkout-terms',max_age=600)
                except signing.BadSignature:
                    reviewed = None
                if reviewed!=fingerprint:
                    raise ValidationError('Hotel terms changed or expired. Open the offer again to review the latest terms.')
        form = forms.PurchaseForm(request.POST if request.method=='POST' else None,kind=offer.kind,
            sandbox=offer.sandbox,rooms=rooms,births=search.get('births'),hotel_config=current,initial={
                'name':request.user.label,'email':request.user.email,'phone':request.user.phone if offer.kind!='hotel' else ''} if not offer.sandbox else {})
        if request.method=='POST' and form.is_valid():
            try:
                limit(request.user,'purchase',20)
                if current is None:
                    price,currency,current = suppliers.prepare(offer,saved)
                    checked_price(offer,price,currency)
                if search.get('topup_order') and not ServiceOrder.objects.filter(
                    pk=search.get('topup_source'),offer__company_id=offer.company_id,offer__kind='esim',
                    status='confirmed',cancellation_requested_at__isnull=True,provider_reference=search['topup_order']).exists():
                    raise ValidationError('This eSIM is no longer eligible for a top-up.')
                details = form.payload(search,suppliers.hotel_rooms(current) if offer.kind=='hotel' else [])
                order,created = credits.reserve(request.user,offer.pk)
                if created:
                    delivery = {'email':details['email'], 'start':search.get('start'), 'end':search.get('end'),
                                'description':saved['row'].get('detail','')}
                    if offer.kind=='esim':
                        delivery['bundle_code']=current['bundle_code']
                    try:
                        reference,confirmed = suppliers.fulfill(order,saved,current,details)
                    except Exception as exc:
                        logging.getLogger(__name__).warning('Service order %s needs review (%s)',order.pk,type(exc).__name__)
                        # A provider write may have succeeded before the response failed.
                        # Never retry it or release credits automatically.
                        reference,confirmed = '',False
                    credits.finish(order.pk,reference,confirmed,delivery)
                return redirect('service_order',order_id=order.pk)
            except QUOTE_ERRORS as exc:
                form.add_error(None,error_text(exc))
    except QUOTE_ERRORS as exc:
        messages.error(request,error_text(exc))
        return redirect('service_catalog',kind=offer.kind)
    groups={}
    contact=[]
    for field in form.visible_fields():
        parts=field.name.split('_')
        if parts[0]=='traveller':
            groups.setdefault(f'Traveller {int(parts[1])+1}',[]).append(field)
        elif parts[0]=='room':
            groups.setdefault(f'Room {int(parts[1])+1} · Guest {int(parts[2])+1}',[]).append(field)
        elif field.name not in ('accept','test_only'):
            contact.append(field)
    return render(request,'portal/service_checkout.html',dict(page_title='Review purchase',offer=offer,
        form=form, contact=contact, checkout_groups=groups.items(), disclosures=disclosures, review_token=review_token, balance=credits.wallet_balance(offer.company_id)))


def authorized_order(user, order_id):
    qs=ServiceOrder.objects.select_related('offer','offer__company','offer__actor')
    if is_ceo(user):
        return get_object_or_404(qs,pk=order_id)
    customer(user)
    qs=qs.filter(offer__company_id=user.company_id)
    if user.role!='owner':
        qs=qs.filter(offer__actor=user)
    return get_object_or_404(qs,pk=order_id)


@login_required
def wallet(request):
    customer(request.user)
    orders = ServiceOrder.objects.filter(offer__company_id=request.user.company_id).select_related('offer')
    if request.user.role!='owner':
        orders=orders.filter(offer__actor=request.user)
    entries=CreditEntry.objects.filter(wallet_id=request.user.company_id).select_related('order')
    if request.user.role!='owner':
        entries=entries.filter(actor=request.user)
    return render(request,'portal/service_wallet.html',dict(page_title='Company credits',
        balance=credits.wallet_balance(request.user.company_id),orders=orders.order_by('-created_at')[:80],
        entries=entries.order_by('-created_at')[:80]))


@login_required
def order_detail(request, order_id):
    order=authorized_order(request.user,order_id)
    return render(request,'portal/service_order.html',dict(page_title='Service order',order=order,
        summary=json.loads(order.delivery or '{}'),balance=credits.wallet_balance(order.offer.company_id)))


@login_required
@require_POST
def refresh(request, order_id):
    order=authorized_order(request.user,order_id)
    try:
        limit(request.user,'refresh',30)
        if order.offer.kind=='hotel' and order.status in ('review','confirmed'):
            data=suppliers.reservation_status(order)
            if str(data.get('clientRef','')).lower()==str(order.pk) and data.get('id') and data.get('status')=='OK':
                with transaction.atomic():
                    locked=ServiceOrder.objects.select_for_update().get(pk=order.pk)
                    if locked.status=='review':
                        locked.provider_reference=str(data['id'])[:160]
                        locked.status='confirmed'
                        locked.save(update_fields=['provider_reference','status'])
                        ServiceOffer.objects.filter(pk=locked.offer_id).update(payload='')
                messages.success(request,'The supplier confirmed this hotel reservation.')
            else:
                messages.info(request,'The supplier has not returned a confirmed reservation. Contact Sama if you need help.')
    except QUOTE_ERRORS as exc:
        messages.error(request,error_text(exc))
    return redirect('service_order',order_id=order.pk)


@login_required
@require_POST
def resend(request, order_id):
    order=authorized_order(request.user,order_id)
    if order.status!='confirmed' or order.offer.kind not in ('esim','insurance'):
        raise Http404
    if order.offer.kind=='insurance' and order.offer.sandbox!=providers.insurance_is_test():
        raise Http404
    try:
        limit(request.user,'resend',8)
        email=json.loads(order.delivery or '{}').get('email')
        if not email:
            raise ValidationError('This order has no delivery email. Contact Sama.')
        result=suppliers.resend(order,email)
        if result.get('status') is False:
            raise ValidationError('The supplier could not resend this email.')
        messages.success(request,'The resend request was sent to the supplier.')
    except QUOTE_ERRORS as exc:
        messages.error(request,error_text(exc))
    return redirect('service_order',order_id=order.pk)


@login_required
def document(request, order_id):
    order=authorized_order(request.user,order_id)
    if order.status!='confirmed' or not order.provider_reference:
        raise Http404
    try:
        limit(request.user,'document',30)
        if order.offer.kind=='insurance':
            if order.offer.sandbox!=providers.insurance_is_test():
                raise Http404
            data=suppliers.insurance_pdf(order.provider_reference)
            filename='test-policy.pdf' if order.offer.sandbox else 'insurance-policy.pdf'
        elif order.offer.kind=='esim':
            from reportlab.graphics.barcode.qr import QrCodeWidget
            from reportlab.graphics.shapes import Drawing
            from reportlab.graphics import renderPDF
            info=suppliers.esim_order(order.provider_reference)
            code=info.get('activation_code')
            if not isinstance(code,str) or not code.startswith('LPA:') or len(code)>1000:
                raise ValidationError('The activation QR is not ready. Try again in a moment or check the supplier email.')
            drawing=Drawing(240,240)
            qr=QrCodeWidget(code,barWidth=240,barHeight=240)
            drawing.add(qr)
            data=renderPDF.drawToString(drawing)
            filename='esim-installation-qr.pdf'
        else:
            data=suppliers.hotel_pdf(order.provider_reference)
            filename='hotel-reservation.pdf'
        return FileResponse(BytesIO(data),as_attachment=True,filename=filename,content_type='application/pdf')
    except QUOTE_ERRORS as exc:
        messages.error(request,error_text(exc))
        return redirect('service_order',order_id=order.pk)


@login_required
def admin_wallet(request, company_id):
    if not is_ceo(request.user):
        raise PermissionDenied
    company=get_object_or_404(Company,pk=company_id)
    form=forms.DepositForm(request.POST if request.method=='POST' else None,initial={'deposit_id':uuid.uuid4()})
    if request.method=='POST' and form.is_valid():
        try:
            credits.deposit(request.user,company.pk,**form.cleaned_data)
            messages.success(request,'The deposit is recorded in the company credit ledger.')
            return redirect('service_admin_wallet',company_id=company.pk)
        except ValidationError as exc:
            form.add_error(None,exc)
    return render(request,'portal/service_wallet.html',dict(page_title='Company credits',company=company,form=form,
        balance=credits.wallet_balance(company.pk),entries=CreditEntry.objects.filter(wallet_id=company.pk).select_related('order').order_by('-created_at')[:80],
        orders=ServiceOrder.objects.filter(offer__company=company).select_related('offer').order_by('-created_at')[:80]))


@login_required
def reconcile(request, order_id):
    if not is_ceo(request.user):
        raise PermissionDenied
    order=authorized_order(request.user,order_id)
    form=forms.ResolveForm(request.POST if request.method=='POST' else None,initial={'reference':order.provider_reference})
    if request.method=='POST' and form.is_valid():
        try:
            credits.resolve(request.user,order.pk,**{k:v for k,v in form.cleaned_data.items() if k!='verified'})
            messages.success(request,'The verified outcome was recorded.')
            return redirect('service_order',order_id=order.pk)
        except ValidationError as exc:
            form.add_error(None,exc)
    return render(request,'portal/form.html',dict(page_title='Reconcile service order',heading='Verify the supplier outcome',
        description='Check the provider portal using the order reference before releasing credits. Never place a second booking to resolve a timeout.',
        form=form,button='Record verified outcome'))


@login_required
@require_POST
def request_cancellation(request, order_id):
    order=authorized_order(request.user,order_id)
    if not credits.allowed(request.user) or order.status!='confirmed':
        raise Http404
    ServiceOrder.objects.filter(pk=order.pk,status='confirmed',cancellation_requested_at__isnull=True).update(
        cancellation_requested_at=timezone.now())
    messages.info(request,'Cancellation requested. Sama will verify eligibility, fees and any refund with the supplier.')
    return redirect('service_order',order_id=order.pk)


@login_required
@require_POST
def esim_options(request, order_id, action):
    customer(request.user)
    order=authorized_order(request.user,order_id)
    if order.offer.kind!='esim' or order.status!='confirmed' or not order.provider_reference:
        raise Http404
    result,offers={},[]
    try:
        limit(request.user,'esim_options',30)
        if action=='usage':
            result=suppliers.usage(order.provider_reference)
        elif action=='topup':
            code=json.loads(order.delivery or '{}').get('bundle_code')
            if not code:
                raise ValidationError('No top-ups are available for this order.')
            query={'topup_order':order.provider_reference,'topup_source':str(order.pk),'topup_bundle':code,'page':1,'sort_by':'price_asc'}
            rows,_=suppliers.esim_catalog(query)
            offers=save_offers(request.user,'esim',rows,query)
            if not offers:
                messages.info(request,'The provider returned no compatible top-ups.')
        else:
            raise Http404
    except QUOTE_ERRORS as exc:
        messages.error(request,error_text(exc))
    return render(request,'portal/service_order.html',dict(page_title='eSIM order',order=order,
        usage=result,topups=offers,balance=credits.wallet_balance(order.offer.company_id)))


@login_required
def review_queue(request):
    if not is_ceo(request.user):
        raise PermissionDenied
    from django.db.models import Q
    from django.core.paginator import Paginator
    orders=ServiceOrder.objects.filter(Q(status__in=['review','processing']) |
        Q(status='confirmed',cancellation_requested_at__isnull=False)).select_related('offer','offer__company')
    page=Paginator(orders.order_by('-created_at'),40).get_page(request.GET.get('page'))
    return render(request,'portal/service_review_queue.html',dict(page_title='Service review',page=page))
