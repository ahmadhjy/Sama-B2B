"""Saved read-only supplier searches shared by chat and choice controls."""
from copy import deepcopy
from django.core.exceptions import ValidationError
from django.db import transaction
from . import concierge, hotel_search, providers
from .chat import estimate, itinerary_changed, invalidate_options
from .models import Draft, TravelRequest
from .auth import allow_attempt


def snapshot(draft):
    return {'trip':draft.summary,'guide':concierge.state(draft.summary),'values':concierge.values(draft.summary),
        'selections':draft.summary.get('selections',{}),'estimate':estimate(draft.summary.get('selections',{})),
        'stale_message_indexes':[i for i,m in enumerate(draft.messages) if m.get('stale')],
        'expired_option_ids':[f'{i}:{j}' for i,m in enumerate(draft.messages) for j,o in enumerate(m.get('options',[])) if o.get('expired')]}


def expire(draft,kind):
    for message in draft.messages:
        for option in message.get('options',[]):
            if option.get('kind')==kind and (option.get('provider') or kind=='flight'): option['expired']=True
    draft.summary.setdefault('selections',{}).pop(kind,None)


def refine(draft,intent):
    journey=draft.summary.setdefault('journey',{})
    previous=journey.get('hotel_criteria',{})
    criteria=hotel_search.merge(previous,intent)
    changed=criteria!=previous
    if changed:
        expire(draft,'hotel');journey['hotel_criteria']=criteria;journey.pop('hotel_places',None);journey.pop('hotel_feedback',None)
        journey['completed']=[k for k in journey.get('completed',[]) if k!='hotel']
        journey['version']=journey.get('version',0)+1
    return changed


def hotel_ready(trip):
    from .hotel_intake import state
    detail=trip.get('journey',{}).get('details',{}).get('hotel',{})
    return (not detail.get('manual') and all(detail.get(k) for k in ('country','city_id','nationality','rooms'))
        and state(trip)['ready'] and trip.get('travellers'))


def hotel_changes(draft,details):
    from . import hotel_intake
    if not isinstance(details,dict) or not any(value is not None and (key!='dates_pending' or value is True) for key,value in details.items()): return False
    previous=deepcopy(draft.summary);revised=deepcopy(previous)
    hotel_intake.apply(revised,details)
    if itinerary_changed(previous,revised):
        intake=deepcopy(revised['journey']['hotel_intake']);shared=deepcopy(revised['journey'].get('context',{}))
        revised['selections']={};invalidate_options(draft.messages);concierge.reset_options(revised,previous)
        revised['journey']['hotel_intake']=intake;revised['journey']['context']=shared
    else:
        expire(draft,'hotel');revised['selections']=draft.summary.get('selections',{})
    revised['journey']['completed']=[k for k in revised['journey'].get('completed',[]) if k!='hotel']
    draft.summary=revised
    return True


def prepare_hotel(draft):
    from . import hotel_intake
    original=deepcopy(draft.summary);revised=deepcopy(original)
    hotel_intake.prepare(revised)
    hotel=hotel_intake.state(revised)
    with transaction.atomic():
        draft=Draft.objects.select_for_update().get(pk=draft.pk)
        if draft.summary!=original or draft.archived or TravelRequest.objects.filter(source_draft=draft).exists():
            raise ValidationError('Your trip changed. Please refresh to continue.')
        if hotel_search.query_fingerprint(original)!=hotel_search.query_fingerprint(revised): expire(draft,'hotel');revised['selections']=draft.summary.get('selections',{})
        draft.summary=revised
        if not hotel['ready']:
            reply={'role':'assistant','content':hotel['question'],'guided':True}
            if not draft.messages or draft.messages[-1].get('content')!=reply['content']: draft.messages.append(reply)
            draft.ai_busy_until=None;draft.save()
            return dict(snapshot(draft),message=reply)
        draft.save()
    return run(draft,'hotel',{})


def run(draft,kind,data,more=False):
    """Caller holds the draft's busy lease. External work runs outside DB transactions."""
    if not allow_attempt(f'provider-offers:{draft.user_id}',30,3600):
        raise ValidationError('Please wait before searching again.')
    with transaction.atomic():
        draft=Draft.objects.select_for_update().get(pk=draft.pk)
        trip=deepcopy(draft.summary);stamp=providers.fingerprint(trip)
        query=hotel_search.query_fingerprint(trip)
        if kind=='hotel':
            saved=trip.get('journey',{}).get('details',{}).get('hotel',{})
            if saved and not saved.get('manual'): data=dict(saved)
            data.pop('_exclude',None)
            if more:
                for message in draft.messages:
                    for option in message.get('options',[]):
                        if option.get('kind')=='hotel' and option.get('provider') and not providers.current(option,trip): option['expired']=True
                selected=draft.summary.get('selections',{}).get('hotel')
                if selected and not providers.current(selected,trip): draft.summary['selections'].pop('hotel',None)
                data['_exclude']=list({o.get('provider_reference',{}).get('hotel_index') for m in draft.messages
                    for o in m.get('options',[]) if o.get('kind')=='hotel' and not m.get('stale') and providers.current(o,trip)
                    and o.get('hotel_fingerprint')==query})
        if not more: expire(draft,kind)
        draft.save()
    try:
        offers=providers.search(kind,trip,data)
        meta=getattr(offers,'search_meta',None) or {}
        for offer in offers:
            offer['trip_fingerprint']=stamp
            if kind=='hotel': offer['hotel_fingerprint']=query
        if kind=='hotel':
            criteria=trip.get('journey',{}).get('hotel_criteria',{})
            description=hotel_search.label(criteria)
            content=(f"{len(offers)} {'more ' if more else ''}hotel option{'s' if len(offers)!=1 else ''} · "+description+'.') if offers else ('No additional matching hotels were returned. ' if more else 'No matching hotels were returned. ')+'Search: '+description+'.'
            if meta.get('point'): content+=' Distances are straight-line.'
            if meta.get('partial'): content+=' More matches may be available.'
            if criteria.get('unverified'): content+=' Sama still needs to verify: '+'; '.join(criteria['unverified'])+'.'
            if not offers: content+=' Change a preference, or let Sama help.'
        else:
            content='Choose an option to include in your request. Nothing is booked.' if offers else 'No offers were returned for these details. You can change them or send the request to Sama for help.'
            if offers and all(o.get('sandbox') for o in offers): content='Choose an insurance option to include in your request. Sama confirms final cover and price. Nothing is booked.'
        message={'role':'assistant','content':content,'options':list(offers),
            'sources':list({o['source_url']:{'url':o['source_url'],'title':o['provider']} for o in offers}.values())}
        places=[]
    except hotel_search.Clarification as exc:
        message={'role':'assistant','content':exc.question,'options':[]};places=exc.places
    with transaction.atomic():
        draft=Draft.objects.select_for_update().get(pk=draft.pk)
        if (providers.fingerprint(draft.summary)!=stamp or (kind=='hotel' and hotel_search.query_fingerprint(draft.summary)!=query)
                or draft.archived or TravelRequest.objects.filter(source_draft=draft).exists()):
            raise ValidationError('Your trip changed during the search. Search again with the updated details.')
        if kind=='hotel':
            journey=draft.summary.setdefault('journey',{});journey['hotel_places']=places;journey['hotel_feedback']=message['content']
        draft.messages.append(message);message['message_index']=len(draft.messages)-1
        draft.ai_busy_until=None;draft.save()
        state=snapshot(draft);message.update({k:state[k] for k in ('selections','estimate','expired_option_ids')})
    return dict(state,message=message,searched_kind=kind)
