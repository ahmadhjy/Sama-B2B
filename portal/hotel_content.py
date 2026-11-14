"""Public-facing hotel content from the supplier's mapping and search feeds."""
import hashlib
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urlencode, urlsplit

from django.conf import settings
from django.core.cache import cache

from . import providers
from .hotel_search import coordinates


def image_url(value):
    if not isinstance(value, str):
        return ''
    try:
        url = urlsplit(value)
    except ValueError:
        return ''
    if url.scheme == 'https' and (
        (url.netloc == 'www.ebookingcenter.com' and url.path.startswith('/tbs/reseller/assets/'))
        or (url.netloc == 'i.travelapi.com' and url.path.startswith('/lodging/'))
    ):
        return value
    return ''


def photos(items):
    result = {}
    for item in items or []:
        if isinstance(item, dict) and (url := image_url(item.get('url'))):
            result.setdefault(url, {'url': url, 'name': providers.plain(item.get('name'), 100)})
    return list(result.values())


def mapping(hotel_id, endpoint, collection=None):
    identity = hashlib.sha256((settings.IRIX_API_BASE_URL + ':' + settings.IRIX_USERNAME).encode()).hexdigest()
    key = f'portal-hotel-content:{identity}:{hotel_id}:{endpoint}'
    result = cache.get(key)
    if result is not None:
        return result
    path = f'/api/mapping/v1/hotels/{hotel_id}/{endpoint}'
    try:
        if collection is None:
            result = providers.call('irix', 'GET', path, timeout=(3, 6))
        else:
            result = []
            for page in range(1, 6):
                data = providers.call('irix', 'GET', path, params={'perPage': 100, 'page': page}, timeout=(3, 6))
                result.extend((data.get('_embedded') or {}).get(collection) or [])
                if page >= int(data.get('_page_count') or 1):
                    break
    except (providers.ProviderUnavailable, AttributeError, TypeError, ValueError):
        return result if collection else {}
    cache.set(key, result, 3600 if result else 120)
    return result


def gallery(hotel_id):
    return photos(mapping(hotel_id, 'images', 'gallery'))


def extended(ref):
    token, srk = ref.get('results_token'), ref.get('srk')
    if not token or not srk:
        return {}
    try:
        return providers.call('irix', 'GET',
            f"/api/hotels/v1/search/results/{quote(str(srk), safe='')}/hotels/{int(ref['hotel_index'])}/details",
            params={'token': token, 'includeExtendedDetails': 1, 'languages[]': ['en_GB']}, timeout=(3, 6))
    except (providers.ProviderUnavailable, KeyError, ValueError, TypeError):
        return {}


def hotel_profile(ref):
    hotel_id = int(ref['hotel_index'])
    with ThreadPoolExecutor(max_workers=6) as pool:
        gallery_future = pool.submit(gallery, hotel_id)
        details_future = pool.submit(mapping, hotel_id, 'details')
        descriptions_future = pool.submit(mapping, hotel_id, 'descriptions')
        facilities_future = pool.submit(mapping, hotel_id, 'facilities', 'facilities')
        categories_future = pool.submit(mapping, hotel_id, 'categories', 'categories')
        extended_future = pool.submit(extended, ref)
    details = dict(details_future.result())
    search_details = extended_future.result()
    descriptions = descriptions_future.result()
    descriptions = descriptions if str(descriptions.get('language', '')).upper().startswith('EN') else {}
    details.update({k: v for k, v in search_details.items() if v})
    rich_text = search_details.get('descriptions') or {}
    rich_images = search_details.get('images') or []
    if isinstance(rich_images, dict):
        rich_images = rich_images.values()
    images = photos([search_details.get('mainImage'), *rich_images, *gallery_future.result()])
    text = providers.plain
    geo = coordinates(details.get('geolocation'))
    map_url = map_embed = ''
    if geo:
        lat, lon = geo['latitude'], geo['longitude']
        map_url = f'https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=16/{lat}/{lon}'
        bounds = (max(-180, lon - .012), max(-90, lat - .006), min(180, lon + .012), min(90, lat + .006))
        params = urlencode({'bbox': ','.join(f'{value:.6f}' for value in bounds),
                            'marker': f'{lat},{lon}', 'layer': 'mapnik'})
        map_embed = 'https://www.openstreetmap.org/export/embed.html?' + params

    def labels(items, limit):
        return list(dict.fromkeys(
            label for item in items if isinstance(item, dict)
            and item.get('visible') is not False and str(item.get('language', 'EN')).upper().startswith('EN')
            if (label := text(item.get('name'), limit))))
    facilities = labels([*(search_details.get('facilities') or []), *facilities_future.result()], 160)
    categories = labels([*(search_details.get('categories') or []), *categories_future.result()], 100)
    address = text(descriptions.get('address') or details.get('address'), 240)
    postal = text(details.get('zipCode'), 20)
    locality = ', '.join(filter(None, (text((details.get(k) or {}).get('name'), 100) for k in ('city', 'country'))))
    if postal and postal not in address:
        address = ' '.join(filter(None, (address, postal)))
    return {
        'address': address, 'locality': locality, 'map_url': map_url, 'map_embed': map_embed, 'photos': images,
        'type': text((details.get('type') or {}).get('name'), 100), 'categories': categories, 'facilities': facilities,
        'overview': text(rich_text.get('full') or descriptions.get('descriptionFull') or rich_text.get('short') or descriptions.get('descriptionShort'), 12000),
        'surroundings': text(rich_text.get('location') or descriptions.get('locationDescription'), 8000),
        'facilities_text': text(rich_text.get('facilities') or descriptions.get('facilitiesDescription'), 8000),
        'rooms_text': text(rich_text.get('rooms') or descriptions.get('roomDescription'), 8000),
        'policies': text(rich_text.get('essentialInformation') or descriptions.get('essentialInformation'), 8000),
    }


def room_content(rates):
    # Load only the rooms attached to the property the customer opened.
    groups = {}
    for rate in rates:
        ref = rate['reference']
        if ref.get('srk') and ref.get('results_token') and ref.get('offer_id') is not None:
            key = (str(ref['offer_id']), ref['srk'], ref['results_token'], ref['hotel_index'])
            groups.setdefault(key, set()).update(str(room['index']) for room in rate['rooms'])

    def fetch(group):
        (offer_id, srk, token, hotel_id), codes = group
        if not codes:
            return offer_id, {}
        path = f"/api/hotels/v1/search/results/{quote(str(srk), safe='')}/hotels/{int(hotel_id)}/offers/{quote(offer_id, safe='')}/rooms"
        try:
            data = providers.call('irix', 'GET', path, params={'token': token, 'roomIndexes': ','.join(sorted(codes))},
                                  timeout=(3, 6))
            return offer_id, {str(room['index']): room for room in data.get('rooms') or []}
        except (providers.ProviderUnavailable, KeyError, TypeError, ValueError, AttributeError):
            return offer_id, {}

    with ThreadPoolExecutor(max_workers=6) as pool:
        info = dict(pool.map(fetch, groups.items()))
    for rate in rates:
        for room in rate['rooms']:
            data = info.get(str(rate['reference'].get('offer_id')), {}).get(str(room['index']), {})
            room.update(providers.room_information(data, room['name'], fallback=room))
            room['photos'] = photos(data.get('images')) or photos(room.get('images'))
