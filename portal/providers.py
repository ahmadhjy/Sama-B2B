"""Read-only provider catalogues. No reservation, contract or purchase endpoints exist here."""
import hashlib
import json
import unicodedata
from html import unescape
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

import pycountry
import requests
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.utils import timezone


class ProviderUnavailable(Exception):
    pass


def countries():
    return sorted([{'code':c.alpha_2, 'name':c.name} for c in pycountry.countries], key=lambda c:c['name'])


def available():
    return {kind:bool(getattr(settings,prefix+'_USERNAME') and getattr(settings,prefix+'_PASSWORD'))
            for kind,prefix in [('hotel','IRIX'),('esim','MONTY_ESIM'),('insurance','SWAN_IMS')]}


def insurance_is_test():
    return settings.SWAN_IMS_SANDBOX or 'staging.' in settings.SWAN_IMS_API_BASE_URL.lower()


def fingerprint(trip):
    return hashlib.sha256(json.dumps({k:str(trip.get(k) or '') for k in
        ('origin','destination','departure','return_date','travellers','service_type')},sort_keys=True).encode()).hexdigest()


def current(offer, trip):
    try:
        age=(timezone.now()-datetime.fromisoformat(offer['quoted_at'])).total_seconds()
        return not offer.get('expired') and 0<=age<=900 and offer['trip_fingerprint']==fingerprint(trip)
    except (KeyError,ValueError,TypeError): return False


def request(method, url, **kwargs):
    if urlparse(url).scheme != 'https':
        raise ProviderUnavailable('The provider requires a secure connection.')
    try:
        response=requests.request(method,url,timeout=(5,30),allow_redirects=False,**kwargs)
        response.raise_for_status()
        if response.status_code != 200: raise ValueError()
        data=response.json()
        if not isinstance(data,dict): raise ValueError()
        return data
    except (requests.RequestException,ValueError,TypeError):
        # Never surface supplier bodies: they can contain credentials or personal information.
        raise ProviderUnavailable('The provider could not return offers. Try again or send your request to Sama.') from None


def session(provider):
    prefix={'irix':'IRIX','monty':'MONTY_ESIM','swan':'SWAN_IMS'}[provider]
    username=getattr(settings,prefix+'_USERNAME');password=getattr(settings,prefix+'_PASSWORD')
    if not username or not password: raise ProviderUnavailable('This provider is not connected yet. Sama can quote it manually.')
    base=getattr(settings,prefix+'_API_BASE_URL').rstrip('/')
    key='portal-provider:'+hashlib.sha256((provider+base+username+password).encode()).hexdigest()
    saved=cache.get(key)
    if saved: return base,saved
    if provider=='irix':
        saved=request('POST',base+'/oauth2/token',data={'grant_type':'client_credentials',
            'scope':'read:mapping read:hotels-search'},auth=(username,password))
    else:
        saved=request('POST',base+('/Agent/login' if provider=='monty' else '/api/v5/login'),
                      json={'username':username,'password':password})
    if not saved.get('access_token'): raise ProviderUnavailable('Provider sign-in failed. Please contact Sama.')
    cache.set(key,saved,max(1,min(int(saved.get('expires_in') or 300)-30,3000)))
    return base,saved


def call(provider, method, path, **kwargs):
    base,auth=session(provider)
    headers={'Accept':'application/json','Authorization':'Bearer '+auth['access_token']}
    if provider=='monty':
        headers={'Accept':'application/json','Access-Token':auth['access_token']}
        kwargs.setdefault('params',{})['reseller_id']=auth['reseller_id']
    if provider=='swan':
        access=(auth.get('user') or {}).get('access') or []
        if not access or not access[0].get('id') or not access[0].get('agency'):
            raise ProviderUnavailable('Insurance agency access is missing. Please contact Sama.')
        headers['Tenant']=str(access[0]['id'])
        if method=='POST': kwargs['json']['agency']=access[0]['agency']
    return request(method,base+path,headers=headers,**kwargs)


def mapping(resource, **params):
    key='portal-mapping:'+hashlib.sha256((settings.IRIX_USERNAME+resource+json.dumps(params,sort_keys=True)).encode()).hexdigest()
    result=cache.get(key)
    if result is None:
        result=call('irix','GET','/api/mapping/v1/'+resource,params=dict(perPage=100,**params))
        cache.set(key,result,3600)
    return (result.get('_embedded') or {}).get(resource,[])


def hotel_cities(name, country=''):
    """Resolve an existing destination before asking for more location details.

    The supplier's name filter is a substring search: Cormeilles-en-Parisis is
    not Paris. Only an exact, unambiguous match may be reused automatically.
    """
    def normalized(value):
        return ''.join(c for c in unicodedata.normalize('NFKD',unescape(value)).casefold() if not unicodedata.combining(c)).strip()
    parents=mapping('countries',iso=country) if country else []
    if country and not parents: return []
    rows=mapping('cities',name=name,**({'countryId':parents[0]['id']} if parents else {}))
    rows=sorted(rows,key=lambda r:(normalized(r['name'])!=normalized(name),normalized(r['name'])))[:12]
    result=[];resolved={str(r['id']):r for r in parents}
    for row in rows:
        parent_id=str(row.get('countryId') or (parents[0]['id'] if parents else ''))
        if not parent_id.isdigit(): continue
        if parent_id not in resolved:
            key='portal-country:'+hashlib.sha256((settings.IRIX_USERNAME+settings.IRIX_API_BASE_URL+parent_id).encode()).hexdigest()
            parent=cache.get(key)
            if parent is None:
                parent=call('irix','GET','/api/mapping/v1/countries/'+parent_id)
                cache.set(key,parent,3600)
            resolved[parent_id]=parent
        parent=resolved[parent_id];iso=str(parent.get('iso') or country).upper()
        nation=pycountry.countries.get(**({'alpha_2':iso} if len(iso)==2 else {'alpha_3':iso}))
        if not nation: continue
        result.append({'id':row['id'],'name':unescape(row['name']),'country':nation.alpha_2,
            'country_name':nation.name,'exact':normalized(row['name'])==normalized(name)})
    return result


def amount(value):
    try:
        number=Decimal(str(value))
        if not number.is_finite() or not 0<number<=10000000: raise ValueError()
        return str(number.quantize(Decimal('.01')))
    except (InvalidOperation,ValueError,TypeError): return None


def option(kind, label, detail, price, currency, reference, *, basis='total', **extra):
    price=amount(price);currency=str(currency or '').upper()
    if not price or not pycountry.currencies.get(alpha_3=currency): return None
    return dict(kind=kind,label=str(label)[:160],detail=str(detail)[:900],price_min=price,price_max=price,
        currency=currency,price_basis=basis,source_url={'hotel':'https://www.ebookingcenter.com/',
        'esim':'https://reseller.montyesim.com/','insurance':settings.SWAN_IMS_API_BASE_URL}[kind],
        provider={'hotel':'IRIX','esim':'Monty eSIM','insurance':'Swan'}[kind],
        provider_reference=reference,quoted_at=timezone.now().isoformat(),**extra)


def search(kind, trip, data):
    """Validate explicit quote inputs. Birth dates are transient and never sent to the model."""
    try:
        country=pycountry.countries.get(alpha_2=str(data.get('country','')).upper())
        if not country: raise ValueError()
        count=int(trip.get('travellers') or 0)
        if not 1<=count<=100: raise ValueError()
        if kind=='esim': return esim(country.alpha_3)
        start=date.fromisoformat(trip.get('departure') or '')
        end=date.fromisoformat(trip.get('return_date') or '')
        if start<timezone.localdate() or end<=start: raise ValueError()
        if kind=='hotel':
            nationality=pycountry.countries.get(alpha_2=str(data.get('nationality','')).upper())
            rooms=data.get('rooms')
            if not nationality or not isinstance(rooms,list) or not 1<=len(rooms)<=10: raise ValueError()
            total=0
            for room in rooms:
                adults=int(room['adults']);ages=room.get('childrenAges',[])
                if not 1<=adults<=9 or not isinstance(ages,list) or len(ages)>8: raise ValueError()
                if any(type(age)!=int or not 0<=age<=18 for age in ages): raise ValueError()
                room.clear();room.update(adults=adults,childrenAges=ages);total+=adults+len(ages)
            if total!=count: raise ValidationError('Room guests must match the trip’s total passengers. Include infants in children’s ages.')
            city_id=int(data.get('city_id') or 0)
            # Resolve city in the selected country server-side; never trust a browser label.
            parent=mapping('countries',iso=country.alpha_2)
            cities=mapping('cities',cityIds=str(city_id),countryId=parent[0]['id']) if parent else []
            if not any(int(c['id'])==city_id for c in cities): raise ValueError()
            return hotels(city_id,nationality.alpha_2,start,end,rooms)
        if kind=='insurance':
            residence=pycountry.countries.get(alpha_2=str(data.get('residence','')).upper())
            births=[date.fromisoformat(v) for v in data.get('birth_dates',[])]
            if not residence or len(births)!=count or any(b>timezone.localdate() or (timezone.localdate()-b).days>120*366 for b in births): raise ValueError()
            return insurance(country.alpha_3,residence.alpha_3,start,end,births)
    except (ValueError,TypeError,KeyError,IndexError,AttributeError):
        raise ValidationError('Check the destination, travel dates and traveller details before searching.') from None
    raise ValidationError('Choose hotels, eSIM or insurance.')


def esim(country):
    data=call('monty','GET','/Bundles',params={'country_code':country,'bundle_category':'country',
        'currency_code':settings.MONTY_ESIM_CURRENCY,'page_number':1,'page_size':50,'sort_by':'price_asc'})
    rows=[]
    for b in data.get('bundles') or []:
        price=next((b[k] for k in ('reseller_retail_price','bundle_price_final','subscriber_price') if b.get(k) is not None),None)
        row=option('esim',b.get('bundle_marketing_name') or b.get('bundle_name') or b.get('bundle_code'),
            f"{country} · {'Unlimited data' if b.get('unlimited') else str(b.get('gprs_limit',''))+' '+str(b.get('data_unit') or 'MB')} · {b.get('validity','?')} days · One eSIM. Choose quantity with Sama.",
            price,settings.MONTY_ESIM_CURRENCY,{'bundle_code':b.get('bundle_code')},basis='per_unit')
        if row and b.get('bundle_code'): rows.append(row)
    return sorted(rows,key=lambda r:Decimal(r['price_min']))[:6]


def insurance(country,residence,start,end,births):
    data=call('swan','POST','/api/v5/travel/plans',json={'country':residence,
        'destinations':[{'country':country,'from_date':str(start),'till_date':str(end)}],
        'travellers':[{'birth_date':str(b)} for b in births]})
    if not data.get('status'): raise ProviderUnavailable('No insurance quote was returned for these travellers. Sama can help.')
    rows=[]
    for plan in data.get('plans') or []:
        matrix=plan.get('price') or []
        if len(matrix)!=len(births): continue
        for tier in ('0','1'):
            prices=[next((p for p in entries if str(p.get('Deductible'))==tier),None) for entries in matrix]
            if any(not p or not amount(p.get('Price')) or p.get('id') is None for p in prices): continue
            total=sum(Decimal(amount(p['Price'])) for p in prices)
            deductible='No deductible' if tier=='0' else 'Deductible: '+', '.join(sorted({str(p.get('DeductiblePrice','See policy')) for p in prices}))
            row=option('insurance',plan.get('print_name') or plan.get('name') or 'Travel insurance',
                f"{start} to {end} · {len(births)} travellers · {deductible} · Policy conditions apply.",
                total,plan.get('currency_code'),{'plan_id':plan.get('id'),'price_ids':[p['id'] for p in prices],'deductible':tier},
                sandbox=insurance_is_test())
            if row: rows.append(row)
    return sorted(rows,key=lambda r:(r['currency'],Decimal(r['price_min'])))[:6]


def hotels(city_id,nationality,start,end,rooms):
    nationalities=mapping('nationalities',iso=nationality)
    if not nationalities: raise ProviderUnavailable('The hotel provider does not recognise this nationality.')
    properties=mapping('hotels',cityId=city_id)
    if not properties: return []
    data=call('irix','POST','/api/hotels/v1/search/sync',json={
        'accommodation':[p['id'] for p in properties[:100]],'checkIn':str(start),'checkOut':str(end),
        'occupancy':{'leaderNationality':nationalities[0]['id'],'rooms':rooms},
        'completeOffersOnly':True,'sellingChannel':'B2B','language':'en_GB','timeout':20,'availableOnly':True})
    rows=[]
    for hotel in data.get('hotels') or []:
        hotel_rows=[]
        for offer in hotel.get('offers') or []:
            room_map={str(r.get('roomCode')):r for r in offer.get('rooms') or []}
            for package in offer.get('packages') or []:
                if package.get('complete') is not True: continue
                price=(package.get('price') or {}).get('selling') or {}
                selected=[]
                for room in package.get('packageRooms') or []:
                    selected += [str(r.get('roomCode')) for r in room.get('roomReferences') or [] if r.get('selected') is True]
                descriptions=[]
                for code in selected:
                    r=room_map.get(code,{})
                    name=r.get('name') or r.get('description')
                    if isinstance(name,str):
                        meal={'RO':'Room only','BB':'Breakfast','HB':'Half board','FB':'Full board','AI':'All inclusive','SC':'Self catering'}.get(r.get('boardBasis'),'Meals to confirm')
                        cancellation='Non-refundable' if r.get('nonRefundable') is True else 'Cancellation conditions apply'
                        descriptions.append(unescape(name)[:160]+' · '+meal+' · '+cancellation)
                detail=f"{start} to {end} · {len(rooms)} room(s) · "+(' / '.join(descriptions) or 'Room package')+'. Sama confirms final terms.'
                row=option('hotel',unescape(hotel.get('name') or 'Hotel'),detail,
                    price.get('value'),price.get('currency'),{'hotel_index':hotel.get('index'),
                    'offer_id':offer.get('id'),'package_code':package.get('packageCode'),
                    'room_codes':selected,'srk':data.get('srk')},stars=hotel.get('stars'))
                if row: hotel_rows.append(row)
        rows.extend(sorted(hotel_rows,key=lambda r:(r['currency'],Decimal(r['price_min'])))[:2])
    return sorted(rows,key=lambda r:(r['currency'],Decimal(r['price_min'])))[:6]
