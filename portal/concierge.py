"""Small, saved conversation steps. These collect preferences, never bookings."""
from copy import deepcopy
from datetime import date, datetime, timedelta
import re
from django.core.exceptions import ValidationError
from django.utils import timezone

SERVICES = {'flight': 'Flights', 'hotel': 'Hotel', 'transfer': 'Transfers',
            'esim': 'eSIM', 'insurance': 'Travel insurance'}
QUESTIONS = {
    'services': 'What would you like us to arrange?',
    'route': 'Where are you travelling from and to?',
    'departure': 'When would you like to leave?',
    'return': 'When does your trip end?',
    'travellers': 'Who is travelling?',
    'flight': 'How would you like to fly?',
    'hotel': 'Let’s find the right hotel for you.',
    'transfer': 'Where do you need a transfer?',
    'esim': 'Where will you use your eSIM?',
    'insurance': 'Let’s check travel cover for your trip.',
    'notes': 'Anything else you would like Sama to know?',
    'ready': 'Your request is ready to review.',
}
CONTEXT_QUESTIONS = {'city': 'Which city would you like to stay in?',
    'country': 'Which country is your destination in?',
    'nationality': 'What is the lead traveller’s nationality?',
    'residence': 'Which country do the travellers live in?'}

REPLY_FIELDS={k:{'type':['string','null']} for k in ('origin','destination','departure','return_date','cabin','airline','transfer_note','note')}
REPLY_FIELDS.update({k:{'type':['integer','null']} for k in ('nights','adults','children','infants')})
REPLY_SCHEMA={'type':['object','null'],'properties':REPLY_FIELDS,'required':list(REPLY_FIELDS),'additionalProperties':False}


def direct_reply(summary,scope,content):
    """Recognise simple intake replies without model latency or ambiguous date guesses."""
    value=content.strip();lower=value.lower()
    if scope=='route':
        city=r"[^\d?!,;:]{2,80}"
        match=re.fullmatch(r'(?:from\s+)?('+city+r')\s+(?:to|→)\s+('+city+r')',value,re.I)
        if match and not re.search(r'\b(want|need|hotel|flight|book|change|show|find)\b',lower):
            return {'origin':match[1].strip(),'destination':match[2].strip()}
        if (re.fullmatch(city,value) and len(value.split())<=4 and
                not re.search(r'\b(i|want|need|hotel|flight|book|change|show|find|what|where|when|instead|please|no|yes|not|near|around|breakfast|stars|prefer)\b',lower)):
            return {'destination' if summary.get('origin') else 'origin':value}
    if scope in ('departure','return'):
        nights=re.fullmatch(r'(?:for\s+)?(\d+)\s+nights?',lower)
        if scope=='return' and nights: return {'nights':int(nights[1])}
        parsed=None;clean=re.sub(r'^(?:on|leaving|returning)\s+','',value,flags=re.I).replace(',','')
        for pattern in ('%Y-%m-%d','%d %B %Y','%d %b %Y','%B %d %Y','%b %d %Y'):
            try: parsed=datetime.strptime(clean,pattern).date();break
            except ValueError: pass
        if lower in ('today','tomorrow'): parsed=timezone.localdate()+timedelta(days=lower=='tomorrow')
        if parsed: return {'departure' if scope=='departure' else 'return_date':parsed.isoformat()}
    if scope=='travellers':
        pattern=r'\b(\d+)\s*(adults?|children|child|kids?|infants?|babies|baby)\b'
        matches=re.findall(pattern,lower)
        remainder=re.sub(pattern,'',lower)
        remainder=re.sub(r'\b(and|with|plus|only|travelling|traveling|passengers|people)\b','',remainder)
        if re.search(r'\w',remainder): return None
        if matches and any(label.startswith('adult') for _,label in matches):
            party={'adults':0,'children':0,'infants':0}
            for number,label in matches:
                key='adults' if label.startswith('adult') else 'children' if label in ('children','child','kid','kids') else 'infants'
                party[key]+=int(number)
            return party
    return None


def chat_answer(summary,scope,reply):
    """Apply only the facts relevant to the current chat question, through normal validation."""
    if not isinstance(reply,dict): return summary,False
    result=deepcopy(summary);done=False
    if scope=='route':
        for key in ('origin','destination'):
            if reply.get(key): result[key]=text(reply[key])
        if result.get('origin') and result.get('destination'):
            result,_=answer(result,'route',{'origin':result['origin'],'destination':result['destination']});done=True
    elif scope=='departure' and reply.get('departure'):
        result,_=answer(result,scope,{'departure':reply['departure']});done=True
    elif scope=='return' and (reply.get('return_date') or reply.get('nights') is not None):
        result,_=answer(result,scope,{'return_date':reply.get('return_date'),'nights':reply.get('nights')});done=True
    elif scope=='travellers' and reply.get('adults') is not None:
        # The model must leave unknown categories null; ask rather than assume children are zero.
        if all(reply.get(k) is not None for k in ('adults','children','infants')):
            result,_=answer(result,scope,{k:reply[k] for k in ('adults','children','infants')});done=True
    elif scope=='flight' and (reply.get('cabin') or reply.get('airline') is not None):
        detail=result.get('journey',{}).get('details',{}).get('flight',{})
        result,_=answer(result,scope,{'cabin':reply.get('cabin') or detail.get('cabin','Economy'),'airline':reply.get('airline') or detail.get('airline','')});done=True
    elif scope=='transfer' and reply.get('transfer_note'):
        result,_=answer(result,scope,{'note':reply['transfer_note']});done=True
    elif scope=='notes' and reply.get('note') is not None:
        result,_=answer(result,scope,{'note':reply['note']});done=True
    return result,done


def question(summary,scope):
    if scope=='route':
        if not summary.get('origin'): return 'Where are you travelling from?'
        if not summary.get('destination'): return 'Where would you like to go?'
    return QUESTIONS.get(scope,'What would you like to change?')


def context(summary):
    shared=dict(summary.get('journey',{}).get('context',{}))
    # Also reuse information collected by earlier versions of the chat.
    for kind,detail in summary.get('journey',{}).get('details',{}).items():
        if detail.get('manual'): continue
        for key in ('country','nationality','residence','city_id','city_name'):
            if key in ('city_id','city_name') and shared.get('country')!=detail.get('country'): continue
            if detail.get(key): shared.setdefault(key,detail[key])
    return shared


def party_label(party):
    return ', '.join(f"{party[k]} {singular if party[k]==1 else plural}" for k,singular,plural in
        [('adults','adult','adults'),('children','child','children'),('infants','infant','infants')])


def return_answer(content,*,at_return=False):
    """Handle explicit date replies without asking a model to update UI state."""
    reply=re.sub(r"[’']",'',content.strip().lower())
    reply=re.sub(r'[.!?]+$','',reply).strip()
    if re.fullmatch(r'(?:a |its |it is )?one[ -]way(?: flight| trip| ticket)?(?: only)?|no return flight(?: needed)?',reply):
        return {'one_way':True,'return_pending':True}
    if reply in ('no return date','no return date yet','no return date for now','no return','return date undecided',
            'return undecided','i dont know the return date yet','i havent decided the return date yet') or (
            at_return and reply in ('undecided','not decided yet','not sure yet','tbd','i dont know','i dont know yet')):
        return {'return_pending':True}
    return None


def reconcile_ai_trip(summary):
    journey=summary.get('journey')
    if not journey: return
    try: total=int(summary.get('travellers') or 0)
    except (ValueError,TypeError): total=0
    party=journey.get('passengers',{})
    if party and sum(party.values())!=total: journey.pop('passengers',None)
    matches=re.findall(r'\b(\d+)\s+(adults?|children|child|kids?|infants?|babies|baby)\b',summary.get('requirements',''),re.I)
    parsed={key:set() for key in ('adults','children','infants')}
    for number,label in matches:
        key='adults' if label.lower().startswith('adult') else 'children' if label.lower() in ('children','child','kid','kids') else 'infants'
        parsed[key].add(int(number))
    if all(len(v)<=1 for v in parsed.values()) and parsed['adults']:
        counts={key:next(iter(v),0) for key,v in parsed.items()}
        if counts['adults']>0 and sum(counts.values())==total: journey['passengers']=counts
    if not any(k in journey.get('services',[]) for k in ('hotel','insurance')) and re.search(r'\bone[ -]way\b',summary.get('requirements',''),re.I) and not summary.get('return_date'):
        journey['one_way']=True


def service_type(services):
    if 'flight' in services and 'hotel' in services: return 'package'
    return next((kind for kind in ('flight', 'hotel', 'transfer') if kind in services), 'travel')


def values(summary):
    result={key:summary.get(key,'') for key in ('title','service_type','origin','destination',
        'departure','return_date','travellers','budget','requirements')}
    journey=summary.get('journey',{})
    date_notes=('One-way travel; no return requested.',
        'Return/end date undecided; Sama to confirm any hotel stay and insurance dates before quoting.')
    result['requirements']='\n'.join(line for line in str(result['requirements'] or '').splitlines()
        if line not in date_notes and not line.startswith(('Hotel search preferences:','For Sama to verify:')))
    services=journey.get('services',[])
    if services: result['service_type']=service_type(services)
    if not result['title'] and result['destination']:
        result['title']=' to '.join(filter(None,[result['origin'],result['destination']]))[:160]
    lines=[]
    if services: lines.append('Services: '+', '.join(SERVICES[k] for k in services))
    party=journey.get('passengers')
    if party:
        lines.append('Travellers: '+party_label(party)+'.')
    if journey.get('one_way'): lines.append('One-way travel; no return requested.')
    if journey.get('return_pending') and not result['return_date']:
        lines.append(date_notes[1])
    for kind, detail in journey.get('details',{}).items():
        if detail.get('manual'):
            lines.append(SERVICES[kind]+': Sama to arrange based on the trip details.')
            continue
        if kind=='flight':
            lines.append('Flights: '+detail['cabin']+'. Airline preference: '+(detail['airline'] or 'No preference')+'.')
        elif kind=='hotel':
            rooms='; '.join(f"Room {i+1}: {r['adults']} adults, children’s ages {', '.join(map(str,r['childrenAges'])) or 'none'}" for i,r in enumerate(detail['rooms']))
            stay=(' Stay: '+detail['check_in']+' to '+detail['check_out']+'.') if detail.get('check_in') and detail.get('check_out') else ''
            lines.append('Hotel: '+detail['city_name']+'.'+stay+' '+rooms+'. '+detail['preferences'])
        elif kind=='transfer': lines.append('Transfer: '+detail['note'])
        elif kind=='esim': lines.append('eSIM destination: '+detail['country'])
        elif kind=='insurance': lines.append('Insurance destination: '+detail['country']+'. Country of residence: '+detail['residence'])
    if journey.get('note'): lines.append('Note for Sama: '+journey['note'])
    if journey.get('hotel_criteria'):
        from .hotel_search import label
        lines.append('Hotel search preferences: '+label(journey['hotel_criteria']))
        lines.extend('For Sama to verify: '+note for note in journey['hotel_criteria'].get('unverified',[]))
    if lines: result['requirements']='\n'.join(dict.fromkeys(line for line in [*str(result['requirements'] or '').strip().splitlines(),*lines] if line))
    result['traveller_details']=''
    return result


def state(summary):
    journey=summary.get('journey',{})
    services=journey.get('services',[])
    try: start=date.fromisoformat(summary.get('departure',''))
    except (ValueError,TypeError): start=None
    try: end=date.fromisoformat(summary.get('return_date',''))
    except (ValueError,TypeError): end=None
    stage='services'
    if services:
        if not summary.get('origin') or not summary.get('destination'): stage='route'
        elif not start or start<timezone.localdate(): stage='departure'
        elif (not end or end<start or ('hotel' in services and end==start)) and not (journey.get('one_way') or journey.get('return_pending')): stage='return'
        elif not journey.get('passengers') or str(sum(journey['passengers'].values()))!=str(summary.get('travellers')): stage='travellers'
        else:
            stage='notes' if not journey.get('notes_done') else 'ready'
            for kind in services:
                if kind not in journey.get('details',{}): stage=kind;break
                if kind not in journey.get('completed',[]): stage=kind if kind=='transfer' else kind+'_options';break
    from .hotel_intake import state as hotel_state
    hotel=hotel_state(summary) if 'hotel' in services else {}
    if services==['hotel']:
        stage=('ready' if journey.get('notes_done') else 'notes') if 'hotel' in journey.get('completed',[]) else 'hotel_options' if hotel.get('ready') else 'hotel'
    elif stage in ('hotel','hotel_options'):
        stage='hotel_options' if hotel.get('ready') else 'hotel'
    return {'step':stage,'question':hotel['question'] if stage=='hotel' else QUESTIONS.get(stage,'Choose an option, or let Sama find it for you.'),
        'services':services,'completed':journey.get('completed',[]),'details':journey.get('details',{}),
        'passengers':journey.get('passengers',{}),'one_way':journey.get('one_way',False),'return_pending':journey.get('return_pending',False),
        'note':journey.get('note',''),'context':context(summary),'version':journey.get('version',0),
        'hotel_criteria':journey.get('hotel_criteria',{}),'hotel_places':[{'id':p['id'],'name':p['name']} for p in journey.get('hotel_places',[])],
        'hotel_feedback':journey.get('hotel_feedback',''),
        'hotel':hotel,
        'can_one_way':not any(k in services for k in ('hotel','insurance'))}


def reset_options(summary,previous=None):
    journey=summary.get('journey')
    if journey:
        shared=context(summary)
        destination_changed=previous is None or previous.get('destination')!=summary.get('destination')
        party_changed=previous is None or str(previous.get('travellers'))!=str(summary.get('travellers')) or previous.get('journey',{}).get('passengers')!=journey.get('passengers')
        if destination_changed:
            for key in ('country','city_id','city_name'): shared.pop(key,None)
            journey.pop('hotel_places',None)
            for key in ('landmark','hotel_name','location_id'): journey.get('hotel_criteria',{}).pop(key,None)
            for key in ('city_id','city_name','country','city_choices','lookup_query','city_query'): journey.get('hotel_intake',{}).pop(key,None)
        if party_changed:
            for key in ('rooms','room_count','adults_by_room','child_ages','child_rooms'): journey.get('hotel_intake',{}).pop(key,None)
        if previous is not None:
            for key,field in [('departure','check_in'),('return_date','check_out')]:
                if previous.get(key)!=summary.get(key): journey.get('hotel_intake',{}).pop(field,None)
        journey['context']=shared
        journey['details']={k:v for k,v in journey.get('details',{}).items()
            if k in ('flight','transfer') or (not destination_changed and (k!='hotel' or not party_changed or v.get('manual')))}
        if summary.get('return_date'):
            journey['details']={k:v for k,v in journey['details'].items() if not v.get('dates_pending')}
        journey['completed']=[k for k in journey.get('completed',[]) if k in journey['details'] and (k=='transfer' or journey['details'][k].get('manual'))]
        journey['version']=journey.get('version',0)+1


def text(value,limit=120,required=True):
    if not isinstance(value,str) or len(value.strip())>limit or (required and not value.strip()):
        raise ValidationError('Please check your answer and try again.')
    return value.strip()


def integer(value,low=0,high=100):
    if type(value) is not int or not low<=value<=high: raise ValidationError('Please check the traveller counts.')
    return value


def day(value):
    try: result=date.fromisoformat(value)
    except (TypeError,ValueError): raise ValidationError('Choose a valid travel date.')
    if result<timezone.localdate(): raise ValidationError('Choose today or a future date.')
    return result


def answer(summary,step,data):
    if not isinstance(data,dict): raise ValidationError('Please check your answer.')
    result=deepcopy(summary)
    journey=result.setdefault('journey',{})
    details=journey.setdefault('details',{})
    completed=journey.setdefault('completed',[])
    if step=='services':
        services=data.get('services')
        if not isinstance(services,list) or not services or len(services)>5 or any(k not in SERVICES for k in services):
            raise ValidationError('Choose at least one service.')
        journey['services']=[k for k in SERVICES if k in services]
        result['selections']={k:v for k,v in result.get('selections',{}).items() if k in services}
        journey['completed']=[k for k in completed if k in services]
        journey['details']={k:v for k,v in details.items() if k in services}
        result['service_type']=service_type(services)
        if any(k in services for k in ('hotel','insurance')): journey['one_way']=False
        label='Services: '+', '.join(SERVICES[k] for k in journey['services'])
    elif step=='route':
        result['origin']=text(data.get('origin'));result['destination']=text(data.get('destination'))
        result['title']=(result['origin']+' to '+result['destination'])[:160]
        label=result['origin']+' → '+result['destination']
    elif step=='departure':
        result['departure']=day(data.get('departure')).isoformat()
        if result.get('return_date') and result['return_date']<result['departure']: result['return_date']=''
        label='Leaving: '+result['departure']
    elif step=='return':
        if not result.get('departure'): raise ValidationError('Choose your departure date first.')
        one_way=data.get('one_way') is True
        pending=data.get('return_pending') is True
        if one_way and not any(k in journey.get('services',[]) for k in ('hotel','insurance')): pending=False
        if one_way and not pending and any(k in journey.get('services',[]) for k in ('hotel','insurance')):
            raise ValidationError('We need an end date for the hotel or insurance.')
        journey['one_way']=one_way
        journey['return_pending']=pending
        if pending:
            result['return_date']=''
            label='One-way flight; stay/cover dates to confirm.' if one_way else 'Return date undecided; Sama to confirm.'
        elif one_way: result['return_date']='';label='One-way trip'
        else:
            end=day(data.get('return_date')) if data.get('return_date') else date.fromisoformat(result['departure'])+timedelta(days=integer(data.get('nights'),1,365))
            if end<date.fromisoformat(result['departure']): raise ValidationError('The end date cannot be before departure.')
            if end==date.fromisoformat(result['departure']) and 'hotel' in journey.get('services',[]):
                raise ValidationError('A hotel stay needs at least one night.')
            result['return_date']=end.isoformat();label='Trip ends: '+result['return_date']
    elif step=='travellers':
        party={key:integer(data.get(key)) for key in ('adults','children','infants')}
        if not 1<=sum(party.values())<=100 or party['adults']<1: raise ValidationError('Add at least one adult, with no more than 100 travellers in total.')
        journey['passengers']=party;result['travellers']=str(sum(party.values()))
        label=party_label(party)
    elif step=='flight':
        cabin=data.get('cabin')
        if cabin not in ('Economy','Premium economy','Business','First'): raise ValidationError('Choose a flight cabin.')
        details['flight']={'cabin':cabin,'airline':text(data.get('airline',''),120,False)}
        completed[:]=[k for k in completed if k!='flight']
        label=cabin+' · '+(details['flight']['airline'] or 'Any airline')
    elif step=='context':
        import pycountry
        key=data.get('field')
        shared=journey.setdefault('context',context(result))
        if key=='city':
            code=text(data.get('country'),2)
            nation=pycountry.countries.get(alpha_2=code)
            if not nation: raise ValidationError('Choose a destination from the suggestions.')
            shared.update(country=code,city_id=text(str(data.get('city_id','')),30),city_name=text(data.get('city_name')))
            label=shared['city_name']+', '+nation.name
        elif key in ('country','nationality','residence'):
            code=text(data.get(key),2);nation=pycountry.countries.get(alpha_2=code)
            if not nation: raise ValidationError('Choose a country from the list.')
            if key=='country' and shared.get('country')!=code:
                shared.pop('city_id',None);shared.pop('city_name',None)
            shared[key]=code;label=nation.name
        else: raise ValidationError('This question is not available.')
    elif step in ('hotel','esim','insurance'):
        import pycountry
        country=text(data.get('country'),2)
        if not pycountry.countries.get(alpha_2=country): raise ValidationError('Choose a destination country.')
        detail={'country':country}
        if step=='hotel':
            detail.update(city_id=text(str(data.get('city_id','')),30),city_name=text(data.get('city_name')),
                nationality=text(data.get('nationality'),2),preferences=text(data.get('preferences',''),1000,False))
            if not pycountry.countries.get(alpha_2=detail['nationality']): raise ValidationError('Choose a nationality.')
            rooms=data.get('rooms')
            if not isinstance(rooms,list) or not 1<=len(rooms)<=10: raise ValidationError('Add between one and ten rooms.')
            clean=[]
            for room in rooms:
                if not isinstance(room,dict): raise ValidationError('Check the room guests.')
                ages=room.get('childrenAges',[])
                if not isinstance(ages,list) or len(ages)>8: raise ValidationError('Check the children’s ages.')
                clean.append({'adults':integer(room.get('adults'),1,9),'childrenAges':[integer(v,0,18) for v in ages]})
            if sum(r['adults']+len(r['childrenAges']) for r in clean)!=int(result.get('travellers') or 0):
                raise ValidationError('Room guests must match your trip’s traveller count.')
            detail['rooms']=clean
            for key in ('check_in','check_out'):
                if data.get(key): detail[key]=day(data[key]).isoformat()
            if detail.get('check_in') and detail.get('check_out') and detail['check_out']<=detail['check_in']:
                raise ValidationError('Check-out needs to be after check-in.')
            if isinstance(data.get('criteria'),dict):
                from .hotel_search import merge
                journey['hotel_criteria']=merge(journey.get('hotel_criteria',{}),data['criteria'])
        if step=='insurance':
            detail['residence']=text(data.get('residence'),2)
            if not pycountry.countries.get(alpha_2=detail['residence']): raise ValidationError('Choose your country of residence.')
        details[step]=detail;completed[:]=[k for k in completed if k!=step]
        shared=journey.setdefault('context',{})
        for key in ('country','nationality','residence','city_id','city_name'):
            if detail.get(key): shared[key]=detail[key]
        label=SERVICES[step]+': '+(detail.get('city_name') or pycountry.countries.get(alpha_2=country).name)
        if step=='hotel':
            label+=' · '+'; '.join(f"Room {i+1}: {r['adults']} adults"+(' · children’s ages '+', '.join(map(str,r['childrenAges'])) if r['childrenAges'] else '') for i,r in enumerate(detail['rooms']))
        if step=='hotel' and detail.get('preferences'): label+=' · '+detail['preferences']
    elif step=='transfer':
        details['transfer']={'note':text(data.get('note','Sama to confirm pickup and drop-off.'),1000)}
        if 'transfer' not in completed: completed.append('transfer')
        label=details['transfer']['note']
    elif step=='skip_service':
        kind=data.get('service')
        if kind not in journey.get('services',[]): raise ValidationError('Choose this service first.')
        details[kind]={'manual':True}
        if kind in ('hotel','insurance') and journey.get('return_pending') and not result.get('return_date'):
            details[kind]['dates_pending']=True
        result.setdefault('selections',{}).pop(kind,None)
        if kind not in completed: completed.append(kind)
        label=SERVICES[kind]+': Sama will find the best option.'
    elif step=='complete_service':
        kind=data.get('service')
        if kind not in journey.get('services',[]) or kind not in details: raise ValidationError('Complete this service’s details first.')
        if not data.get('skip') and kind not in result.get('selections',{}): raise ValidationError('Choose an option or ask Sama to find one.')
        if kind not in completed: completed.append(kind)
        label=SERVICES[kind]+(': Sama will find the best option.' if data.get('skip') else ': preferred option saved.')
    elif step=='notes':
        journey['note']=text(data.get('note',''),2000,False);journey['notes_done']=True
        label=journey['note'] or 'No additional requests.'
    else: raise ValidationError('This step is not available.')
    journey['version']=journey.get('version',0)+1
    return result,label
