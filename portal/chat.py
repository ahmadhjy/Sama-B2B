"""Saved, sourced travel preferences used by the chat workspace."""
from decimal import Decimal, InvalidOperation


def itinerary_changed(previous, current):
    fields = ('origin', 'destination', 'departure', 'return_date', 'travellers', 'service_type')
    return any(str(previous.get(k) or '').strip().lower() != str(current.get(k) or '').strip().lower()
               for k in fields if k in current)


def option_groups(messages, selections=None):
    selections = selections or {}
    result = []
    for index, message in enumerate(messages):
        groups = []
        for kind, title in [('flight', 'Flight options'), ('hotel', 'Hotel options'), ('esim', 'eSIM plans'), ('insurance', 'Travel insurance'), ('travel', 'Travel options')]:
            options = []
            for number, raw in enumerate(message.get('options', [])):
                if raw.get('kind', 'travel') != kind:
                    continue
                option = dict(raw, id=f'{index}:{number}', stale=message.get('stale', False) or raw.get('expired'))
                option['selected'] = selections.get(kind, {}).get('id') == option['id']
                options.append(option)
            if options:
                groups.append({'kind': kind, 'title': title, 'options': options})
        result.append(dict(message, option_groups=groups))
    return result


def invalidate_options(messages):
    for message in messages:
        if message.get('options'):
            message['stale'] = True


def preference_text(selections):
    lines = []
    for kind, option in selections.items():
        price_label='Indicative provider price' if option.get('sandbox') else 'Provider price'
        price = f"\n{price_label}: {option.get('price_min')} {option.get('currency')} ({option.get('price_basis')})" if option.get('provider') else ''
        test_note=' (Sama confirms final cover and price)' if option.get('sandbox') else ''
        hotel_details=''
        if kind=='hotel':
            facts=([str(option['stars'])+' stars'] if option.get('stars') else [])
            facts.extend(r['name']+': '+r['size'] for r in option.get('room_details',[]) if r.get('size'))
            if facts: hotel_details='\nHotel details: '+'; '.join(facts)
        reference = f"\nProvider reference: {option.get('provider_reference')} · Quoted: {option.get('quoted_at')}" if option.get('provider') else ''
        lines.append(f"Preferred {kind}: {option['label']}{test_note} — {option['detail']}{hotel_details}{price}{reference}\nSource: {option['source_url']}")
    return '\n'.join(lines)


def estimate(selections):
    """Only add prices explicitly scoped to the complete requested party/stay."""
    choices = list(selections.values())
    if not choices or any(v.get('sandbox') or v.get('price_basis') != 'total' for v in choices):
        return None
    currencies = {v.get('currency') for v in choices}
    if len(currencies) != 1 or not next(iter(currencies)):
        return None
    try:
        low = sum(Decimal(str(v['price_min'])) for v in choices)
        high = sum(Decimal(str(v['price_max'])) for v in choices)
    except (KeyError, InvalidOperation, TypeError):
        return None
    if not low.is_finite() or not high.is_finite() or low <= 0 or high < low:
        return None
    return {'low': str(low), 'high': str(high), 'currency': next(iter(currencies))}
