"""Saved conversational hotel intake: supplier requirements, never a preference wizard."""
from copy import deepcopy
import re
import pycountry
from django.core.exceptions import ValidationError
from . import concierge, providers

FIELDS={key:{'type':['string','null']} for key in ('city','country','nationality','check_in','check_out')}
FIELDS.update({key:{'type':['integer','null']} for key in ('nights','adults','children','infants','room_count','room_adults','room','age')})
FIELDS['child_ages']={'type':['array','null'],'items':{'type':'integer'}}
FIELDS['dates_pending']={'type':['boolean','null']}
FIELDS['rooms']={'type':['array','null'],'items':{'type':'object','properties':{
    'adults':{'type':'integer'},'childrenAges':{'type':'array','items':{'type':'integer'}}},
    'required':['adults','childrenAges'],'additionalProperties':False}}
SCHEMA={'type':['object','null'],'properties':FIELDS,'required':list(FIELDS),'additionalProperties':False}


def country_code(value):
    if not isinstance(value,str): return ''
    clean=value.strip().lower().replace('’',"'")
    clean=re.sub(r"^(?:i am|i'm|we are|we're|we live in|i live in|my nationality is|from)\s+",'',clean).rstrip('. ')
    aliases={'lebanese':'LB','french':'FR','british':'GB','english':'GB','american':'US','turkish':'TR','emirati':'AE','uk':'GB','usa':'US','uae':'AE'}
    try: return pycountry.countries.lookup(aliases.get(clean,clean)).alpha_2
    except LookupError: return ''


def saved(summary):
    journey=summary.get('journey',{});detail=journey.get('details',{}).get('hotel',{})
    result=dict(concierge.context(summary))
    if not detail.get('manual'): result.update(detail)
    result.update(journey.get('hotel_intake',{}))
    result.setdefault('city_query',summary.get('destination',''))
    result.setdefault('check_in',summary.get('departure',''))
    result.setdefault('check_out',summary.get('return_date',''))
    return result


def state(summary):
    data=saved(summary);party=summary.get('journey',{}).get('passengers',{})
    choices=[];field='ready';question='Choose a hotel, or tell me what you’d like to change.'
    try: start=concierge.day(data.get('check_in'));valid_start=True
    except ValidationError: start=None;valid_start=False
    try: end=concierge.day(data.get('check_out'));valid_end=bool(start and end>start)
    except ValidationError: valid_end=False
    if not data.get('city_id'):
        field='city';question='Which city would you like to stay in?'
        choices=[{'label':p['name']+', '+p['country_name'],'value':str(p['id'])} for p in data.get('city_choices',[])]
    elif not valid_start: field='check_in';question='When would you like to check in?'
    elif not valid_end: field='check_out';question='When will you check out, or how many nights will you stay?'
    elif not party: field='party';question='How many adults, children and infants are staying?'
    elif not data.get('nationality'): field='nationality';question='What is the lead traveller’s nationality?'
    elif not data.get('rooms'):
        young=party.get('children',0)+party.get('infants',0)
        count=data.get('room_count')
        if not count:
            field='room_count';question='How many rooms for '+concierge.party_label(party)+'?'
            choices=[{'label':f'{n} room'+('s' if n!=1 else ''),'value':n} for n in range(max(1,(party['adults']+8)//9,(young+7)//8),min(10,party['adults'])+1)]
        elif len(data.get('adults_by_room',[]))<count:
            field='room_adults';question=f"How many adults will stay in room {len(data.get('adults_by_room',[]))+1}?"
        elif len(data.get('child_ages',[]))<young:
            field='age';question=f"How old will child or infant {len(data.get('child_ages',[]))+1} be at check-in?"
        elif len(data.get('child_rooms',[]))<young:
            field='room';question=f"Which room will child or infant {len(data.get('child_rooms',[]))+1} stay in?"
            choices=[{'label':f'Room {n}','value':n} for n in range(1,count+1)]
    return {'field':field,'question':question,'choices':choices,'ready':field=='ready',
        'known':{k:v for k,v in data.items() if k not in ('city_choices','lookup_query')},'pending_dates':bool(summary.get('journey',{}).get('return_pending') and not data.get('check_out'))}


def direct(summary,content,field=None):
    field=field or state(summary)['field'];value=content.strip()
    if field=='check_out' and concierge.return_answer(value,at_return=True): return {'dates_pending':True}
    if field=='party': return concierge.direct_reply(summary,'travellers',value)
    if field=='nationality':
        code=country_code(value)
        if code: return {'nationality':code}
    if field in ('room_count','room_adults','room','age'):
        clean=re.sub(r"^(?:he's|she's|he is|she is|room|aged|age)\s+",'',value.lower().replace('’',"'"))
        words=['zero','one','two','three','four','five','six','seven','eight','nine','ten']
        for number,word in enumerate(words): clean=re.sub(r'\b'+word+r'\b',str(number),clean)
        match=re.fullmatch(r'(\d+)\s*(?:rooms?|adults?|years?(?: old)?)?[.!]?',clean)
        if match: return {field:int(match[1])}
    if field in ('check_in','check_out'):
        found=concierge.direct_reply(summary,'departure' if field=='check_in' else 'return',value)
        if found: return {field:found.get('departure') or found.get('return_date')} if 'nights' not in found else found
    return None


def apply(summary,reply):
    if not isinstance(reply,dict): return
    journey=summary.setdefault('journey',{});data=journey.setdefault('hotel_intake',{})
    old=saved(summary);party=dict(journey.get('passengers',{}));previous=deepcopy(party)
    if old.get('rooms'):
        rooms=old['rooms'];data.setdefault('room_count',len(rooms))
        data.setdefault('adults_by_room',[r['adults'] for r in rooms])
        data.setdefault('child_ages',[a for r in rooms for a in r['childrenAges']])
        data.setdefault('child_rooms',[i+1 for i,r in enumerate(rooms) for a in r['childrenAges']])
    for key in ('adults','children','infants'):
        if reply.get(key) is not None: party[key]=concierge.integer(reply[key],1 if key=='adults' else 0,100)
    if party.get('adults'):
        party={k:party.get(k,0) for k in ('adults','children','infants')}
        if sum(party.values())>100: raise ValidationError('Please keep the request to 100 travellers or fewer.')
        journey['passengers']=party;summary['travellers']=str(sum(party.values()))
        if previous and party!=previous:
            for key in ('rooms','room_count','adults_by_room','child_ages','child_rooms'): data.pop(key,None)
            journey.get('details',{}).pop('hotel',None)
    if reply.get('city'):
        city=concierge.text(reply['city'])
        if city.casefold() not in (str(old.get('city_name','')).casefold(),str(old.get('city_query','')).casefold()):
            for key in ('city_id','city_name','country','city_choices','lookup_query'): data.pop(key,None);journey.setdefault('context',{}).pop(key,None)
            journey.get('details',{}).pop('hotel',None)
        data['city_query']=city
        if not summary.get('destination') or journey.get('services')==['hotel']: summary['destination']=city
    for key in ('country','nationality'):
        if reply.get(key) is not None:
            code=country_code(reply[key])
            if not code: raise ValidationError('Please tell me the country name or its two-letter code.')
            if key=='country' and code!=old.get('country'):
                for field in ('city_id','city_name','city_choices','lookup_query'): data.pop(field,None);journey.setdefault('context',{}).pop(field,None)
                journey.get('details',{}).pop('hotel',None)
            data[key]=code;journey.setdefault('context',{})[key]=code
    for key,trip_key in [('check_in','departure'),('check_out','return_date')]:
        if reply.get(key):
            data[key]=concierge.day(reply[key]).isoformat()
            if not summary.get(trip_key) or journey.get('services')==['hotel']: summary[trip_key]=data[key]
    if reply.get('nights') is not None:
        from datetime import date,timedelta
        start=data.get('check_in') or old.get('check_in')
        if not start: raise ValidationError('What is your check-in date?')
        calculated=(date.fromisoformat(start)+timedelta(days=concierge.integer(reply['nights'],1,365))).isoformat()
        if reply.get('check_out') and calculated!=data.get('check_out'): raise ValidationError('The check-out date and number of nights differ. Which check-out date should I use?')
        data['check_out']=calculated
        if not summary.get('return_date') or journey.get('services')==['hotel']: summary['return_date']=data['check_out']
    if reply.get('room_count') is not None:
        count=concierge.integer(reply['room_count'],1,10)
        if count!=old.get('room_count',len(old.get('rooms',[]))):
            for key in ('rooms','adults_by_room','child_rooms'): data.pop(key,None)
            journey.get('details',{}).pop('hotel',None)
        data['room_count']=count
    if reply.get('rooms') is not None:
        if not isinstance(reply['rooms'],list) or not 1<=len(reply['rooms'])<=10: raise ValidationError('Please describe the guests in each room.')
        rooms=[]
        for room in reply['rooms']:
            if not isinstance(room,dict) or not isinstance(room.get('childrenAges'),list) or len(room['childrenAges'])>8: raise ValidationError('Please include the adults and children’s ages for each room.')
            rooms.append({'adults':concierge.integer(room.get('adults'),1,9),'childrenAges':[concierge.integer(a,0,18) for a in room['childrenAges']]})
        if party and (sum(r['adults'] for r in rooms)!=party['adults'] or sum(len(r['childrenAges']) for r in rooms)!=party.get('children',0)+party.get('infants',0)):
            raise ValidationError('The adults and children in the rooms must match your trip’s guests.')
        data['rooms']=rooms;data['room_count']=len(rooms)
    if reply.get('child_ages') is not None:
        if not isinstance(reply['child_ages'],list): raise ValidationError('Please tell me the children’s ages.')
        data['child_ages']=[concierge.integer(age,0,18) for age in reply['child_ages']]
        if party and len(data['child_ages'])>party.get('children',0)+party.get('infants',0): raise ValidationError('There are more child ages than children and infants. Please check the guest counts.')
        data.pop('rooms',None);journey.get('details',{}).pop('hotel',None)
    for key,store,low,high in [('room_adults','adults_by_room',1,9),('age','child_ages',0,18),('room','child_rooms',1,10)]:
        if reply.get(key) is not None:
            if key=='age' and state(summary)['field']!=key and party.get('children',0)+party.get('infants',0)==1:
                data['child_ages']=[concierge.integer(reply[key],low,high)];data.pop('rooms',None);journey.get('details',{}).pop('hotel',None);continue
            if state(summary)['field']!=key: raise ValidationError('Please describe the full room allocation if you want to change it.')
            data.setdefault(store,[]).append(concierge.integer(reply[key],low,high))
    dates=saved(summary)
    if dates.get('check_in') and dates.get('check_out') and dates['check_out']<=dates['check_in']:
        raise ValidationError('Check-out needs to be after check-in.')
    if reply.get('dates_pending') is True:
        data['check_out']='';journey['return_pending']=True
        if journey.get('services')==['hotel']: summary['return_date']=''
    elif reply.get('check_out') or reply.get('nights') is not None: journey['return_pending']=False
    allocate(summary)
    journey['version']=journey.get('version',0)+1


def prepare(summary):
    """Resolve supplier city IDs and reuse known facts; never invent occupancy."""
    journey=summary.setdefault('journey',{});data=journey.setdefault('hotel_intake',{})
    current=saved(summary);query=current.get('city_query','')
    if not current.get('city_id') and query and current.get('lookup_query')!=query:
        cities=providers.hotel_cities(query,current.get('country',''))
        data['lookup_query']=query;data['city_choices']=cities
        exact=[c for c in cities if c.get('exact')]
        if len(exact)==1: choose_city(summary,str(exact[0]['id']))
    allocate(summary)
    if state(summary)['ready']:
        current=saved(summary)
        detail={key:current.get(key,'') for key in ('country','city_id','city_name','nationality','rooms','check_in','check_out')}
        detail['preferences']=''
        revised,_=concierge.answer(summary,'hotel',detail)
        checked=revised['journey']['details']['hotel']
        if checked!=journey.get('details',{}).get('hotel'):
            journey.setdefault('details',{})['hotel']=checked
            journey['completed']=[k for k in journey.get('completed',[]) if k!='hotel']
            journey['version']=journey.get('version',0)+1


def allocate(summary):
    journey=summary.setdefault('journey',{});data=journey.setdefault('hotel_intake',{})
    current=saved(summary);party=journey.get('passengers',{})
    young=party.get('children',0)+party.get('infants',0);adults=party.get('adults',0)
    if adults and not current.get('rooms'):
        if adults==1 and young<=8: data.setdefault('room_count',1)
        count=data.get('room_count')
        if count:
            if count>adults or adults>count*9 or young>count*8: raise ValidationError('This room allocation does not fit your guests. Please change the room count or let Sama arrange it.')
            allocation=data.setdefault('adults_by_room',[])
            if len(allocation)<count and (sum(allocation)+(count-len(allocation))>adults or sum(allocation)+9*(count-len(allocation))<adults):
                raise ValidationError('Each room needs at least one adult. Please check this room’s guest count.')
            if count==1: allocation[:]=[adults]
            elif count==adults: allocation[:]=[1]*count
            elif len(allocation)==count-1:
                remaining=adults-sum(allocation)
                if not 1<=remaining<=9: raise ValidationError('Please check the adults in each room.')
                allocation.append(remaining)
            if sum(allocation)>adults or len(allocation)>count: raise ValidationError('The rooms have more adults than the trip. Please tell me the room count again.')
            if count==1: data['child_rooms']=[1]*young
            if len(allocation)==count and len(data.get('child_ages',[]))==young and len(data.get('child_rooms',[]))==young:
                rooms=[{'adults':n,'childrenAges':[]} for n in allocation]
                for age,room in zip(data.get('child_ages',[]),data.get('child_rooms',[])):
                    if room>count: raise ValidationError('That room number is not part of your allocation.')
                    rooms[room-1]['childrenAges'].append(age)
                data['rooms']=rooms


def choose_city(summary,city_id):
    journey=summary.setdefault('journey',{});data=journey.setdefault('hotel_intake',{})
    city=next((c for c in data.get('city_choices',[]) if str(c['id'])==str(city_id)),None)
    if not city: raise ValidationError('Choose a city from the suggestions in this conversation.')
    for key,value in dict(country=city['country'],city_id=str(city['id']),city_name=city['name']).items():
        data[key]=value;journey.setdefault('context',{})[key]=value
    data.pop('city_choices',None)
