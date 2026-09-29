"""Broadnet GW3N HTTP API (provider guide, pp. 7-13). No credentials in URLs."""
import re
import unicodedata
from urllib.parse import urlparse

import requests
from django.conf import settings


class SMSRejected(Exception):
    """A definitive, sanitized provider rejection; safe to show in Operations."""


class SMSUncertain(Exception):
    """Submission may have reached the provider. Do not automatically resend."""


def mobile(value):
    number = re.sub(r'[\s().-]', '', value)
    if number.startswith('+'):
        number = number[1:]
    elif number.startswith('00'):
        number = number[2:]
    if not re.fullmatch(r'[1-9][0-9]{7,14}', number):
        raise SMSRejected('SMS_INVALID_INTERNATIONAL_NUMBER')
    return number


def endpoint(path):
    base = settings.SMS_BASE_URL.rstrip('/')
    parts = urlparse(base)
    if parts.scheme not in ('https', 'http') or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise SMSRejected('SMS_INVALID_ENDPOINT')
    if parts.scheme == 'http' and not settings.SMS_ALLOW_HTTP:
        raise SMSRejected('SMS_HTTP_REQUIRES_EXPLICIT_CONFIGURATION')
    return base + '/' + path


def approval_text(name, link):
    name = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode()
    name = re.sub(r'[^A-Za-z0-9 .-]', ' ', name).strip()[:28] or 'A teammate'
    suffix = ' requests quote approval. ' + link
    remaining = 160 - len(suffix)
    if remaining < 1:
        raise SMSRejected('SMS_PORTAL_LINK_TOO_LONG')
    return name[:remaining] + suffix


def submit(number, text):
    destination = mobile(number)
    if not settings.SMS_USERNAME or not settings.SMS_PASSWORD:
        raise SMSRejected('SMS_CREDENTIALS_MISSING')
    if not re.fullmatch(r'(?:[A-Za-z][A-Za-z0-9 ]{0,10}|[0-9]{1,15})', settings.SMS_SENDER_ID):
        raise SMSRejected('SMS_SENDER_ID_MISSING_OR_INVALID')
    # GW3N type 1 is English, up to 160 characters; these characters are restricted/extended.
    if not text or len(text) > 160 or any(ord(c) < 32 or ord(c) > 126 or c in '&#[\\]{}|~^`' for c in text):
        raise SMSRejected('SMS_INVALID_ENGLISH_MESSAGE')
    url = endpoint('websms')
    try:
        response = requests.post(url, data={'user': settings.SMS_USERNAME, 'pass': settings.SMS_PASSWORD,
            'sid': settings.SMS_SENDER_ID, 'mno': destination, 'type': '1', 'text': text},
            timeout=(5, 20), allow_redirects=False)
    except requests.RequestException:
        raise SMSUncertain('SMS_SUBMISSION_OUTCOME_UNKNOWN') from None
    body = response.text.strip()
    error = re.search(r'ERROR\s*-\s*(HTTP\d{2})\b', body)
    if error:
        raise SMSRejected(error.group(1))
    if response.status_code == 200 and re.fullmatch(r'[0-9]{1,80}', body):
        return body
    raise SMSUncertain('SMS_UNRECOGNIZED_SUBMISSION_RESPONSE')


def status(message_id):
    if not re.fullmatch(r'[0-9]{1,80}', message_id):
        raise SMSRejected('SMS_INVALID_MESSAGE_ID')
    try:
        response = requests.get(endpoint('websmsstatus'), params={'respid': message_id},
            timeout=(5, 10), allow_redirects=False)
        response.raise_for_status()
    except requests.RequestException:
        raise SMSUncertain('SMS_STATUS_UNAVAILABLE') from None
    value = response.text.strip().upper()
    if value not in ('ATES', 'DELIVRD', 'UNDELIV', 'EXPIRED', 'REJECTD', 'ACCEPTD', 'DELETED', 'UNKNOWN'):
        raise SMSUncertain('SMS_UNRECOGNIZED_STATUS_RESPONSE')
    return value


def balance():
    """Read-only account check. POST keeps credentials out of query strings."""
    try:
        response = requests.post(endpoint('balanceReport'), data={
            'userid': settings.SMS_USERNAME, 'password': settings.SMS_PASSWORD},
            timeout=(5, 15), allow_redirects=False)
        response.raise_for_status()
    except requests.RequestException:
        raise SMSUncertain('SMS_BALANCE_UNAVAILABLE') from None
    text = response.text.strip()
    error = re.search(r'ERROR\s*-\s*(HTTP\d{2})\b', text)
    if error:
        raise SMSRejected(error.group(1))
    # Do not print arbitrary provider bodies which may echo authentication parameters.
    match = re.fullmatch(r'(?:Balance\s*[:=]?\s*)?([0-9]+(?:\.[0-9]+)?)(?:\s*(?:CRD|CREDITS))?', text, re.I)
    if not match:
        raise SMSUncertain('SMS_BALANCE_FORMAT_UNVERIFIED')
    return match.group(1)
