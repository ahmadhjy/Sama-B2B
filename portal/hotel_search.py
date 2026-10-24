"""Validated hotel-search preferences and read-only IRIX destination searches."""
from copy import deepcopy
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
import math
import re
import time
import unicodedata

from django.core.exceptions import ValidationError


FIELDS = {
    'landmark': {'type':['string','null']},
    'hotel_name': {'type':['string','null']},
    'stars': {'type':['array','null'],'items':{'type':'integer','minimum':1,'maximum':5}},
    'board_basis': {'type':['string','null'],'enum':['any','RO','BB','HB','FB','AI','SC',None]},
    'refundability': {'type':['string','null'],'enum':['any','refundable','non_refundable',None]},
    'radius_km': {'type':['number','null'],'minimum':0.1,'maximum':50},
    'sort': {'type':['string','null'],'enum':['price','distance','stars','recommended',None]},
    'unverified': {'type':['array','null'],'items':{'type':'string'}},
    'more': {'type':'boolean'}, 'reset': {'type':'boolean'},
}
INTENT_SCHEMA={'type':['object','null'],'properties':FIELDS,'required':list(FIELDS),'additionalProperties':False}
DEFAULTS={'landmark':'','hotel_name':'','stars':[],'board_basis':'any','refundability':'any',
    'radius_km':1.0,'sort':'price','unverified':[]}


def query_fingerprint(trip):
    journey=trip.get('journey',{})
    return hashlib.sha256(json.dumps({'criteria':journey.get('hotel_criteria',{}),
        'details':journey.get('details',{}).get('hotel',{})},sort_keys=True).encode()).hexdigest()


def package_matches(rooms,criteria):
    if not rooms: return False
    board=criteria.get('board_basis','any');refund=criteria.get('refundability','any')
    return all((board=='any' or r.get('boardBasis')==board) and
        (refund=='any' or r.get('nonRefundable') is (refund=='non_refundable')) for r in rooms)


class Clarification(Exception):
    def __init__(self,question,places=None):
        self.question=question;self.places=places or []


def normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFKD',str(value)).casefold() if not unicodedata.combining(c)).strip()


def merge(previous,intent):
    if not isinstance(intent,dict): raise ValidationError('Please describe the hotel options you need.')
    result=deepcopy(DEFAULTS if intent.get('reset') is True else dict(DEFAULTS,**(previous or {})))
    for key in ('landmark','hotel_name'):
        value=intent.get(key)
        if value is not None:
            if not isinstance(value,str) or len(value.strip())>120: raise ValidationError('Please shorten the hotel or place name.')
            if result[key]!=value.strip() and key=='landmark': result.pop('location_id',None)
            result[key]=value.strip()
    if intent.get('stars') is not None:
        stars=intent['stars']
        if not isinstance(stars,list) or len(stars)>5 or any(type(s) is not int or not 1<=s<=5 for s in stars):
            raise ValidationError('Choose hotel ratings from one to five stars.')
        result['stars']=sorted(set(stars))
    for key,allowed in [('board_basis',('any','RO','BB','HB','FB','AI','SC')),
            ('refundability',('any','refundable','non_refundable')),('sort',('price','distance','stars','recommended'))]:
        if intent.get(key) is not None:
            if intent[key] not in allowed: raise ValidationError('Please check the hotel preferences.')
            result[key]=intent[key]
    if intent.get('radius_km') is not None:
        radius=intent['radius_km']
        if type(radius) not in (int,float) or not math.isfinite(radius) or not .1<=radius<=50:
            raise ValidationError('Choose a distance between 0.1 and 50 km.')
        result['radius_km']=float(radius)
    if intent.get('unverified') is not None:
        notes=intent['unverified']
        if not isinstance(notes,list) or len(notes)>8 or any(not isinstance(n,str) or len(n)>160 for n in notes):
            raise ValidationError('Please shorten the remaining hotel preferences.')
        result['unverified']=list(dict.fromkeys(n.strip() for n in notes if n.strip()))
    return result


def basic_intent(text):
    """A transparent fallback for simple replies when the model is unavailable."""
    result={};text=text.strip()
    stars=re.search(r'\b([1-5])\s*[- ]?stars?\b',text,re.I)
    negated=bool(re.search(r"\b(no|not|without|avoid|don.t)\b",text,re.I))
    if stars and not negated:
        rating=int(stars[1]);result['stars']=list(range(rating,6)) if re.search(r'\b(and above|or higher|or better|at least)\b',text,re.I) else [rating]
    if not negated and re.search(r'\b(breakfast|bed and breakfast)\b',text,re.I): result['board_basis']='BB'
    if re.search(r'\bnon[- ]?refundable\b',text,re.I): result['refundability']='non_refundable'
    elif not negated and re.search(r'\b(refundable|free cancellation)\b',text,re.I): result['refundability']='refundable'
    near=re.search(r'\b(?:near|close to|around)\s+(.+?)(?:[,;]|\s+with\b|$)',text,re.I)
    if near and not negated: result['landmark']=near[1].strip()[:120]
    radius=re.search(r'\b(?:within\s+)?(\d+(?:\.\d+)?)\s*(km|kilomet(?:er|re)s?|met(?:er|re)s?|m)\b',text,re.I)
    if radius: result['radius_km']=float(radius[1])/(1000 if radius[2].lower() in ('m','meter','meters','metre','metres') else 1)
    # Do not pretend that an unparsed request has been applied.
    if text: result['unverified']=['Additional preferences for Sama to verify: '+text[:110]]
    return result


def label(criteria):
    parts=[]
    if criteria.get('landmark'): parts.append(f"within {criteria.get('radius_km',1):g} km of {criteria['landmark']}")
    if criteria.get('hotel_name'): parts.append('hotel name: '+criteria['hotel_name'])
    if criteria.get('stars'): parts.append('/'.join(map(str,criteria['stars']))+' stars')
    board={'BB':'breakfast included','RO':'room only','HB':'half board','FB':'full board','AI':'all inclusive','SC':'self catering'}.get(criteria.get('board_basis'))
    if board: parts.append(board)
    if criteria.get('refundability')=='refundable': parts.append('refundable options')
    if criteria.get('refundability')=='non_refundable': parts.append('non-refundable options')
    if criteria.get('sort')=='price': parts.append('lowest price first')
    if criteria.get('sort')=='distance' and criteria.get('landmark'): parts.append('nearest checked matches first')
    if criteria.get('sort')=='stars': parts.append('highest rating first')
    return ' · '.join(parts) or 'available hotels for your trip'


def coordinates(value):
    try:
        lat=float(value['latitude']);lon=float(value['longitude'])
        if math.isfinite(lat) and math.isfinite(lon) and -90<=lat<=90 and -180<=lon<=180:
            return {'latitude':lat,'longitude':lon}
    except (TypeError,KeyError,ValueError): pass
    return None


def distance(first,second):
    a,b=map(math.radians,(first['latitude'],second['latitude']))
    dlat=b-a;dlon=math.radians(second['longitude']-first['longitude'])
    return 6371*2*math.asin(min(1,math.sqrt(math.sin(dlat/2)**2+math.cos(a)*math.cos(b)*math.sin(dlon/2)**2)))


def resolve_place(city_id,criteria):
    from . import providers as p
    target=criteria.get('landmark','')
    if not target: return None
    if re.search(r'\b(?:city cent(?:re|er)|downtown)\b',normalized(target)) or normalized(target) in ('centre','center'):
        city=p.call('irix','GET',f'/api/mapping/v1/cities/{int(city_id)}')
        point=coordinates(city.get('geolocation'))
        if point: return dict(point,name=target,id=0)
    if criteria.get('location_id'):
        places=[p.call('irix','GET',f"/api/mapping/v1/locations/{int(criteria['location_id'])}")]
    else:
        shorter=re.sub(r'\b(square|station|airport|meydani|meydanı)\b','',normalized(target)).strip()
        places=[]
        for query in dict.fromkeys([target,shorter]):
            if len(query)<2: continue
            places=p.mapping('locations',cityId=int(city_id),name=query)
            if places: break
    candidates=[]
    for place in places:
        point=coordinates(place.get('geolocation'))
        if not point or str(place.get('cityId'))!=str(city_id) or (place.get('services') and 'hotel' not in place['services']): continue
        if not any(distance(point,prior)<.05 for prior in candidates):
            candidates.append(dict(point,id=int(place['id']),name=p.plain(place.get('name'),120)))
    if len(candidates)==1: return candidates[0]
    if candidates: raise Clarification('Which place did you mean? Choose the location for your hotel search.',candidates[:8])
    raise Clarification(f'I couldn’t match “{target}” to a location in the hotel provider’s catalogue. Try a nearby district or another landmark name.')


def conversational_intent(previous,text,intent):
    """Ground new places in the client's words and honour explicit requests to broaden."""
    clean=normalized(text);result={k:deepcopy(v) for k,v in (intent or {}).items() if v is not None and (k not in ('more','reset') or v is True)}
    broad=re.search(r'\b(?:anything|any hotel|any hotels|whatever)\b.*\b(?:in|within|anywhere)\b',clean)
    qualified=re.search(r'\b(?:with|near|close|stars?|breakfast|refundable|inclusive|pool|under|cheaper|less|at least|budget)\b|\b\d+\b',clean)
    if (broad and not qualified) or clean in ('anything is fine','show anything','any hotel is fine'):
        return {'reset':True}
    if re.search(r'\b(?:anywhere|within the city|within city|any area|whole city|no area preference)\b',clean):
        result['landmark']=''
    if re.search(r'\bany hotels?\b',clean): result['hotel_name']=''
    value=result.get('landmark')
    if value and value!=previous.get('landmark'):
        words=set(re.findall(r'\w+',normalized(value)))-{'square','the','in','city','centre','center'}
        supplied=set(re.findall(r'\w+',clean))
        central=bool(re.search(r'\b(?:central|centre|center|downtown)\b',clean))
        if not words.intersection(supplied):
            if central: result['landmark']='city centre'
            else: result.pop('landmark',None)
    name=result.get('hotel_name')
    if name and name!=previous.get('hotel_name'):
        words=set(re.findall(r'\w+',normalized(name)))-{'hotel','hotels','the','in'}
        if not words.intersection(re.findall(r'\w+',clean)): result.pop('hotel_name',None)
    return result or None


def fetch(city_id,nationality,start,end,rooms,criteria,exclude=()):
    """Search the supplier's full destination inventory, then load matching offers."""
    from . import providers as p
    deadline=time.monotonic()+90
    def remote(method,path,**kwargs):
        remaining=deadline-time.monotonic()
        if remaining<=0: raise p.ProviderUnavailable('This hotel search is taking too long. Please try again or let Sama help.')
        kwargs['timeout']=(3,min(12,max(.1,remaining)))
        return p.call('irix',method,path,**kwargs)
    criteria=merge(criteria,{});point=resolve_place(city_id,criteria)
    if criteria['sort']=='distance' and not point: raise Clarification('Which landmark should I use to find the nearest hotels?')
    destination={'geofence':dict(point,radius=criteria['radius_km'])} if point else {'city':{'id':int(city_id)}}
    if point: destination['geofence']={k:v for k,v in destination['geofence'].items() if k in ('latitude','longitude','radius')}
    filters={}
    if criteria['hotel_name']: filters['name']=criteria['hotel_name']
    if criteria['stars']: filters['classification']=criteria['stars']
    initial=remote('POST','/api/hotels/v1/search/start',json={
        'destination':destination,'checkIn':str(start),'checkOut':str(end),
        'occupancy':{'leaderNationality':nationality,'rooms':rooms},'completeOffersOnly':True,
        'sellingChannel':'B2B','language':'en_GB','timeout':20,'availableOnly':True,**({'filters':filters} if filters else {})})
    tokens=dict(initial.get('tokens') or {});srk=initial.get('srk');status=initial.get('status')
    if not isinstance(srk,str) or not re.fullmatch(r'[A-Za-z0-9-]+',srk) or not tokens.get('results'):
        raise p.ProviderUnavailable('The hotel search could not start. Please try again.')
    for attempt in range(12):
        if status in ('COMPLETED','ERROR'): break
        if not tokens.get('progress'): break
        time.sleep(1 if attempt<2 else 2)
        status=remote('GET','/api/hotels/v1/search/progress',params={'token':tokens['progress']}).get('status')
    if status!='COMPLETED': raise p.ProviderUnavailable('The hotel provider has not completed this search. Try again in a moment; the previous cards are not new results.')
    params={'token':tokens['results'],'perPage':100,'includeHotelDetails':1,'sortField':criteria['sort'] if criteria['sort'] in ('stars','recommended') else 'price','sortOrder':'DESC' if criteria['sort'] in ('stars','recommended') else 'ASC'}
    if criteria['board_basis']!='any': params['boardBasis[]']=[criteria['board_basis']]
    if criteria['refundability']=='refundable': params['excludeNonRefundable']=1
    candidates=[];properties=[];missing_coordinates=0;excluded={str(i) for i in exclude};seen=set()
    total_pages=1;read_pages=0
    for page in range(1,4):
        result=remote('GET',f'/api/hotels/v1/search/results/{srk}',params=dict(params,page=page))
        read_pages=page;total_pages=int((result.get('pages') or {}).get('total') or 1)
        for hotel in result.get('hotels') or []:
            details=hotel.get('details') or {};hotel_id=hotel.get('index')
            if str(hotel_id) in excluded or hotel_id in seen: continue
            seen.add(hotel_id)
            name=str(hotel.get('name') or details.get('name') or '')
            stars=hotel.get('stars') if hotel.get('stars') is not None else details.get('stars')
            if criteria['hotel_name'] and normalized(criteria['hotel_name']) not in normalized(name): continue
            if criteria['stars'] and stars not in criteria['stars']: continue
            km=None
            if point:
                geo=coordinates(details.get('geolocation'))
                if not geo: missing_coordinates+=1;continue
                km=distance(point,geo)
                if km>criteria['radius_km']+.001: continue
            prop=dict(details,id=hotel_id,name=name,stars=stars)
            properties.append(prop);candidates.append(dict(hotel,index=hotel_id,name=name,stars=stars,_distance=km))
        if len(candidates)>=24 or page>=total_pages: break
    if point and not candidates and missing_coordinates:
        raise p.ProviderUnavailable('The provider did not supply enough hotel coordinates to verify this distance. Sama can check the location, or you can change the search.')
    if criteria['sort']=='distance': candidates.sort(key=lambda h:h['_distance'])
    limited=len(candidates)>24;candidates=candidates[:24]
    def load(hotel):
        try:
            data=remote('GET',f"/api/hotels/v1/search/results/{srk}/hotels/{int(hotel['index'])}/offers",params={'token':tokens['results']})
            return dict(hotel,offers=data.get('offers') or [])
        except p.ProviderUnavailable: return None
    with ThreadPoolExecutor(max_workers=4) as pool: loaded=list(pool.map(load,candidates))
    hotels=[hotel for hotel in loaded if hotel is not None]
    if candidates and not hotels: raise p.ProviderUnavailable('The hotel provider could not load prices for this search. Please try again; this does not mean the hotels are sold out.')
    meta={'label':label(criteria),'point':point,'criteria':criteria,
        'partial':read_pages<total_pages or limited or len(hotels)<len(candidates),'unverified':criteria['unverified'],
        'distances':{str(h['index']):h['_distance'] for h in hotels if h['_distance'] is not None}}
    return {'srk':srk,'tokens':{'results':tokens['results']},'hotels':hotels},properties,meta
