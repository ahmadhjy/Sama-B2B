"""Small, saved conversation steps. These collect preferences, never bookings."""
from copy import deepcopy
from datetime import date, timedelta
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


def party_label(party):
    return ', '.join(f"{party[k]} {singular if party[k]==1 else plural}" for k,singular,plural in
        [('adults','adult','adults'),('children','child','children'),('infants','infant','infants')])


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
    for kind, detail in journey.get('details',{}).items():
        if detail.get('manual'):
            lines.append(SERVICES[kind]+': Sama to arrange based on the trip details.')
            continue
        if kind=='flight':
            lines.append('Flights: '+detail['cabin']+'. Airline preference: '+(detail['airline'] or 'No preference')+'.')
        elif kind=='hotel':
            rooms='; '.join(f"Room {i+1}: {r['adults']} adults, children’s ages {', '.join(map(str,r['childrenAges'])) or 'none'}" for i,r in enumerate(detail['rooms']))
            lines.append('Hotel: '+detail['city_name']+'. '+rooms+'. '+detail['preferences'])
        elif kind=='transfer': lines.append('Transfer: '+detail['note'])
    if journey.get('note'): lines.append('Note for Sama: '+journey['note'])
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
        elif (not end or end<start or ('hotel' in services and end==start)) and not journey.get('one_way'): stage='return'
        elif not journey.get('passengers') or str(sum(journey['passengers'].values()))!=str(summary.get('travellers')): stage='travellers'
        else:
            stage='notes' if not journey.get('notes_done') else 'ready'
            for kind in services:
                if kind not in journey.get('details',{}): stage=kind;break
                if kind not in journey.get('completed',[]): stage=kind if kind=='transfer' else kind+'_options';break
    return {'step':stage,'question':QUESTIONS.get(stage,'Choose an option, or let Sama find it for you.'),
        'services':services,'completed':journey.get('completed',[]),'details':journey.get('details',{}),
        'passengers':journey.get('passengers',{}),'one_way':journey.get('one_way',False),
        'note':journey.get('note',''),'version':journey.get('version',0),
        'can_one_way':not any(k in services for k in ('hotel','insurance'))}


def reset_options(summary):
    journey=summary.get('journey')
    if journey:
        journey['completed']=[]
        journey['details']={k:v for k,v in journey.get('details',{}).items() if k in ('flight','transfer') and not v.get('manual')}
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
        if one_way and any(k in journey.get('services',[]) for k in ('hotel','insurance')):
            raise ValidationError('We need an end date for the hotel or insurance.')
        journey['one_way']=one_way
        if one_way: result['return_date']='';label='One-way trip'
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
        if step=='insurance':
            detail['residence']=text(data.get('residence'),2)
            if not pycountry.countries.get(alpha_2=detail['residence']): raise ValidationError('Choose your country of residence.')
        details[step]=detail;completed[:]=[k for k in completed if k!=step]
        label=SERVICES[step]+': '+(detail.get('city_name') or pycountry.countries.get(alpha_2=country).name)
    elif step=='transfer':
        details['transfer']={'note':text(data.get('note','Sama to confirm pickup and drop-off.'),1000)}
        if 'transfer' not in completed: completed.append('transfer')
        label=details['transfer']['note']
    elif step=='skip_service':
        kind=data.get('service')
        if kind not in journey.get('services',[]): raise ValidationError('Choose this service first.')
        details[kind]={'manual':True}
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
