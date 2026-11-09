"""Supplier operations for explicit manual purchases; never retry a billable write."""
from datetime import date
from urllib.parse import quote, urljoin, urlsplit

import requests

from django.conf import settings
from django.core.exceptions import ValidationError

from . import providers


def enabled(kind, sandbox=False):
    if kind == 'insurance':
        host=urlsplit(settings.SWAN_IMS_API_BASE_URL).hostname
        if sandbox:
            return bool(host and host.startswith('staging.') and providers.insurance_is_test())
        if providers.insurance_is_test():
            return False
    return bool(getattr(settings, f'SERVICE_{kind.upper()}_CHECKOUT'))


def esim_catalog(criteria):
    params = {k: v for k, v in criteria.items() if v and k in (
        'country_code', 'region_code', 'bundle_category', 'bundle_name', 'profile_type', 'sort_by')}
    params.update(currency_code=settings.MONTY_ESIM_CURRENCY, page_size=50, page_number=criteria.get('page', 1))
    if criteria.get('topup_bundle'):
        params['bundle_code']=criteria['topup_bundle']
    data = providers.call('monty', 'GET', '/Bundles/AvailableTopup' if criteria.get('topup_bundle') else '/Bundles', params=params)
    offers = []
    for bundle in data.get('bundles') or []:
        code = bundle.get('bundle_code')
        if not code:
            continue
        currency = settings.MONTY_ESIM_CURRENCY.upper()
        if bundle.get('additional_currency_code') == currency:
            fields = ('reseller_retail_price_in_additional_currency','subscriber_price_in_additional_currency')
        elif currency == 'USD':
            fields = ('reseller_retail_price','subscriber_price')
        else:
            continue
        price = next((bundle[k] for k in fields if bundle.get(k) is not None), None)
        detail = ' · '.join(str(v) for v in [
            'Unlimited data' if bundle.get('unlimited') else f"{bundle.get('gprs_limit','')} {bundle.get('data_unit','MB')}",
            f"{bundle.get('validity','?')} days", bundle.get('profile_type'), bundle.get('bundle_category'),
            'Calls and SMS' if bundle.get('supports_calls_sms') else 'Data only',
            'Top-up supported' if bundle.get('support_topup') else '',
        ] if v)
        row = providers.option('esim', bundle.get('bundle_marketing_name') or bundle.get('bundle_name') or code,
                               detail, price, currency, {'bundle_code': str(code)})
        if row:
            offers.append(row)
    return offers, int(data.get('total_bundles_count') or len(offers))


def insurance_quotes(data):
    return providers.insurance(data['destination'], data['residence'], date.fromisoformat(data['start']),
                               date.fromisoformat(data['end']), [date.fromisoformat(v) for v in data['births']], limit=None)


def hotel_path(ref):
    return '/api/hotels/v1/search/results/{}/hotels/{}/offers/{}'.format(
        *(quote(str(ref[key]), safe='') for key in ('srk','hotel_index','offer_id')))


def prebook(ref):
    if not all(ref.get(k) for k in ('results_token','package_token','room_tokens')) or not all(ref['room_tokens']):
        raise ValidationError('This hotel rate cannot be booked online. Choose another rate.')
    data = providers.call('irix','POST',hotel_path(ref)+'/availability',
        params={'token':ref['results_token']}, json={'packageToken':ref['package_token'],'roomTokens':ref['room_tokens']})
    package = data.get('package') or {}
    if not data.get('availabilityToken') or package.get('complete') is not True:
        raise ValidationError('This hotel rate is no longer available. Search again.')
    return data


def hotel_price(prebook_data):
    return ((prebook_data.get('price') or {}).get('selling') or (prebook_data['package'].get('price') or {}).get('selling') or {})


def hotel_rooms(prebook_data):
    rooms = []
    for room in prebook_data['package'].get('packageRooms', []):
        tokens = [r['roomToken'] for r in room.get('roomReferences', []) if r.get('selected') and r.get('roomToken')]
        occupancy = room.get('occupancy') or {}
        if len(tokens) != 1 or not occupancy.get('adults'):
            raise ValidationError('This room configuration cannot be booked online.')
        rooms.append({'token':tokens[0], 'adults':int(occupancy['adults']), 'ages':occupancy.get('childrenAges') or []})
    if not rooms:
        raise ValidationError('This room configuration cannot be booked online.')
    return rooms


def hotel_credit_supported(data):
    methods = data.get('paymentMethods') or {}
    credit = methods.get('credit') if isinstance(methods,dict) else next(
        (m for m in methods if isinstance(m,dict) and m.get('code')=='credit'),None)
    info = (credit or {}).get('info') or {}
    if not credit or info.get('active') is False or info.get('enabled') is False:
        return False
    available=info.get('available') or {}
    price=hotel_price(data)
    if info.get('unlimited') is not True and available.get('currency')==price.get('currency') and available.get('value') is not None:
        from decimal import Decimal, InvalidOperation
        try:
            return Decimal(str(available['value'])) >= Decimal(str(price['value']))
        except (InvalidOperation,KeyError):
            return False
    return True


def prepare(offer, saved):
    row, search = saved['row'], saved['search']
    ref = row['provider_reference']
    if offer.kind == 'hotel':
        data = prebook(ref)
        price = hotel_price(data)
        if any(extra.get('mandatory') for group in (data.get('extraServices') or []) for extra in group.get('services',[])):
            raise ValidationError('This hotel requires a separately priced service. Ask Sama to confirm the full cost.')
        if not hotel_credit_supported(data):
            raise ValidationError('Supplier credit payment is unavailable for this rate. Choose another rate or contact Sama.')
        return price.get('value'), price.get('currency'), data
    if offer.kind == 'insurance':
        match = next((r for r in insurance_quotes(search) if all(
            r['provider_reference'][k] == ref[k] for k in ('plan_id','deductible'))), None)
    else:
        match = None
        results, _ = esim_catalog(search)
        match = next((r for r in results if r['provider_reference']['bundle_code'] == ref['bundle_code']), None)
    if not match:
        raise ValidationError('This offer is no longer available. Search again.')
    return match['price_min'], match['currency'], match['provider_reference']


def fulfill(order, saved, current, details):
    kind = order.offer.kind
    search = saved['search']
    if not enabled(kind,order.offer.sandbox):
        raise ValidationError('The supplier checkout environment changed.')
    if kind == 'esim':
        payload={'bundle_code':current['bundle_code'],'order_reference':str(order.pk)}
        if details.get('phone'):
            payload['whatsapp_number']=details['phone']
        if search.get('topup_order'):
            payload['order_id']=search['topup_order']
        else:
            payload.update(email=details['email'],name=details['name'])
        data = providers.call('monty','POST','/Bundles/Topup' if search.get('topup_order') else '/Bundles',
                              params={'currency_code':order.offer.currency},json=payload)
        reference = data.get('order_id')
        confirmed = bool(reference)
    elif kind == 'insurance':
        travellers = [dict(person,birth_date=birth,plan_price_id=price_id)
                      for person,birth,price_id in zip(details['travellers'],search['births'],current['price_ids'],strict=True)]
        data = providers.call('swan','POST','/api/v5/travel/contract',json={
            'country':search['residence'],'plan_id':current['plan_id'],'email':details['email'],
            'phone':details['phone'],'address':details['address'],'travellers':travellers,
            'destinations':[{'country':search['destination'],'from_date':search['start'],'till_date':search['end']}]})
        reference = (data.get('contract') or {}).get('contract_code') or data.get('contract_code') or data.get('contract_id')
        confirmed = bool(reference) and data.get('status') in (True, 'success')
    else:
        ref = saved['row']['provider_reference']
        data = providers.call('irix','POST',hotel_path(ref)+'/book',scope='write:hotels-book',
            params={'token':ref['results_token']}, json={
                'availabilityToken':current['availabilityToken'],'clientRef':str(order.pk),
                'payment':{'method':'credit'},'rooms':details['rooms'],'comments':details['notes'],
                'bookingOptions':details['booking_options'],'supplierBookingForm':details['supplier_form']})
        reference = data.get('id')
        confirmed = bool(reference) and data.get('status') == 'OK'
    return str(reference or '')[:160], confirmed


def reservation_status(order):
    return providers.call('irix','GET',f'/api/reservationsApi/v1/reservations/reference/{order.pk}',scope='read:reservations')


def esim_order(reference):
    data = providers.call('monty','GET','/Orders',params={'order_id':reference,'page_size':1,'page_number':1})
    return next((row for row in data.get('orders',[]) if str(row.get('order_id')) == reference), {})


def resend(order, email):
    if order.offer.kind == 'esim':
        return providers.call('monty','POST','/Orders/ResendEmail',json={'order_id':order.provider_reference})
    return providers.call('swan','POST','/api/v5/travel/contract/email',
        json={'code':order.provider_reference,'email':email,'attachments':['contract','receipt','general_conditions']})


def insurance_pdf(reference):
    base, auth = providers.session('swan')
    if not base.startswith('https://'):
        raise providers.ProviderUnavailable('The insurance provider requires HTTPS.')
    try:
        headers={'Authorization':'Bearer '+auth['access_token'],'Tenant':str(auth['user']['access'][0]['id'])}
    except (KeyError,IndexError,TypeError):
        raise providers.ProviderUnavailable('Insurance agency access is missing.') from None
    return fetch_pdf(base+'/api/v5/travel/contract/pdf', params={'code':reference}, headers=headers)


def fetch_pdf(url, **kwargs):
    try:
        with requests.get(url,timeout=(5,25),allow_redirects=False,stream=True,**kwargs) as response:
            if response.status_code != 200:
                raise ValueError()
            output = bytearray()
            for chunk in response.iter_content(65536):
                output.extend(chunk)
                if len(output) > 10_000_000:
                    raise ValueError()
            if not output.startswith(b'%PDF-'):
                raise ValueError()
            return bytes(output)
    except (requests.RequestException, KeyError, IndexError, TypeError, ValueError):
        raise providers.ProviderUnavailable('The policy PDF is not available yet.') from None


def hotel_pdf(reference):
    if not reference.isascii() or not reference.isdecimal():
        raise providers.ProviderUnavailable('The hotel reservation reference is invalid.')
    path=f'/api/reservationsApi/v1/reservations/{reference}/documents'
    scope='read:reservations-documents'
    data=providers.call('irix','GET',path,scope=scope)
    docs=data.get('documents') or []
    tokens=[item.get('token') for group in docs for item in group.get('documents',[]) if item.get('token')]
    if not tokens:
        raise providers.ProviderUnavailable('The hotel document is not available yet.')
    generated=providers.call('irix','GET',path+'/generate',params={'token':tokens[0]},scope=scope)
    base=settings.IRIX_API_BASE_URL.rstrip('/')
    href=((generated.get('_links') or {}).get('download') or {}).get('href','')
    url=urljoin(base+'/',href)
    parsed, original=urlsplit(url),urlsplit(base)
    if (parsed.scheme,parsed.netloc)!=('https',original.netloc) or not (
            parsed.path.startswith(original.path+'/downloadServiceJwt/') or '/reseller/downloadServiceJwt/' in parsed.path):
        raise providers.ProviderUnavailable('The hotel document link could not be verified.')
    return fetch_pdf(url)


def usage(reference):
    data=providers.call('monty','GET','/Orders/Consumption',params={'order_id':reference})
    if data.get('status') is False:
        raise providers.ProviderUnavailable('Usage is not available yet.')
    return {k:data[k] for k in ('data_used','data_remaining','data_unit','minutes_remaining','sms_remaining',
                               'plan_status','bundle_expiry_date','unlimited') if k in data}


def regions():
    from django.core.cache import cache
    key='service-regions:'+settings.MONTY_ESIM_API_BASE_URL
    result=cache.get(key)
    if result is None:
        data=providers.call('monty','GET','/AvailableRegions')
        result=[(str(r['region_code']),str(r['region_name'])) for r in data.get('regions',[])
                if r.get('region_code') and r.get('region_name')]
        cache.set(key,result,3600)
    return result
