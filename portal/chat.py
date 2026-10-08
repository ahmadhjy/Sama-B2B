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
        for kind, title in [('flight', 'Flight options'), ('hotel', 'Hotel options'), ('travel', 'Travel options')]:
            options = []
            for number, raw in enumerate(message.get('options', [])):
                if raw.get('kind', 'travel') != kind:
                    continue
                option = dict(raw, id=f'{index}:{number}', stale=message.get('stale', False))
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
        lines.append(f"Preferred {kind}: {option['label']} — {option['detail']}\nSource: {option['source_url']}")
    return '\n'.join(lines)


def estimate(selections):
    """Only add prices explicitly scoped to the complete requested party/stay."""
    choices = [v for k, v in selections.items() if k in ('flight', 'hotel')]
    if not choices or any(v.get('price_basis') != 'total' for v in choices):
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
