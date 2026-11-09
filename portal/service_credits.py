"""Wallet transactions and durable checkout state."""
import json
from decimal import Decimal, InvalidOperation, ROUND_UP

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .models import CreditEntry, CreditWallet, ServiceOffer, ServiceOrder, User
from .permissions import is_ceo

CENT = Decimal('0.01')


def allowed(user):
    return bool(user.is_authenticated and user.is_active and not user.removed_at and user.company_id
                and user.role in (User.Role.OWNER, User.Role.HR))


def credits_for(price, currency, sandbox=False):
    if sandbox:
        return Decimal('0.00')
    try:
        rate = Decimal('1') if currency == 'USD' else Decimal(str(json.loads(settings.SERVICE_CREDIT_USD_RATES)[currency]))
        if not rate.is_finite() or rate <= 0:
            return None
        cost = (Decimal(str(price))*rate).quantize(CENT, rounding=ROUND_UP)
        return cost if 0 < cost <= 10_000_000 else None
    except (InvalidOperation, ValueError, TypeError, KeyError):
        return None


def wallet_balance(company_id):
    return CreditWallet.objects.filter(pk=company_id).values_list('balance',flat=True).first() or Decimal('0.00')


def locked_wallet(company_id):
    CreditWallet.objects.get_or_create(company_id=company_id)
    return CreditWallet.objects.select_for_update().get(pk=company_id)


@transaction.atomic
def deposit(actor, company_id, amount, note, deposit_id):
    if not is_ceo(actor):
        raise PermissionDenied
    if not amount.is_finite() or amount != amount.quantize(CENT) or not 0 < amount <= 10_000_000 or not note.strip():
        raise ValidationError('Enter a positive credit amount and a deposit reference.')
    wallet = locked_wallet(company_id)
    existing = CreditEntry.objects.filter(deposit_id=deposit_id).first()
    if existing:
        if (existing.wallet_id, existing.amount, existing.note) != (wallet.pk, amount, note):
            raise ValidationError('This deposit form was already used. Open a new form.')
        return
    if wallet.balance + amount >= 10**12:
        raise ValidationError('The company balance would exceed its limit.')
    wallet.balance += amount
    wallet.save(update_fields=['balance'])
    CreditEntry.objects.create(wallet=wallet, actor=actor, amount=amount, note=note, kind='deposit', deposit_id=deposit_id)


@transaction.atomic
def reserve(actor, offer_id):
    actor=User.objects.select_for_update().get(pk=actor.pk)
    if not allowed(actor) or not actor.company.active:
        raise PermissionDenied
    try:
        offer = ServiceOffer.objects.select_for_update().get(pk=offer_id, actor=actor, company_id=actor.company_id)
    except ServiceOffer.DoesNotExist:
        raise ValidationError('This offer expired. Search again.') from None
    existing = ServiceOrder.objects.filter(offer=offer).first()
    if existing:
        return existing, False
    if offer.expires <= timezone.now() or offer.credits is None:
        raise ValidationError('The quote expired or has no credit price. Search again.')
    if credits_for(offer.price, offer.currency, offer.sandbox) != offer.credits:
        raise ValidationError('The credit price has changed. Search again.')
    wallet = locked_wallet(offer.company_id)
    if wallet.balance < offer.credits:
        raise ValidationError('The company does not have enough credits. Contact Sama to add credits.')
    order = ServiceOrder.objects.create(offer=offer)
    if offer.credits:
        wallet.balance -= offer.credits
        wallet.save(update_fields=['balance'])
        CreditEntry.objects.create(wallet=wallet, actor=actor, order=order, kind='purchase', amount=-offer.credits)
    return order, True


@transaction.atomic
def finish(order_id, reference, confirmed, delivery):
    order = ServiceOrder.objects.select_for_update().get(pk=order_id)
    if order.status != 'processing':
        return
    order.status = 'confirmed' if confirmed and reference else 'review'
    order.provider_reference = reference
    order.delivery = json.dumps(delivery)
    order.save(update_fields=['status','provider_reference','delivery'])
    if order.status == 'confirmed':
        ServiceOffer.objects.filter(pk=order.offer_id).update(payload='')


@transaction.atomic
def resolve(actor, order_id, decision, reference, note, refund=None):
    if not is_ceo(actor):
        raise PermissionDenied
    order = ServiceOrder.objects.select_for_update().get(pk=order_id)
    if order.status=='confirmed' and order.cancellation_requested_at:
        if decision!='cancelled' or refund is None:
            raise ValidationError('Record the verified cancellation and the actual credit refund (zero if none).')
    else:
        if order.status != 'review' and not (order.status == 'processing' and
                (timezone.now()-order.created_at).total_seconds() >= 900):
            raise ValidationError('This order cannot be reconciled now.')
        if decision not in ('confirmed','released') or (decision=='confirmed' and not reference.strip()):
            raise ValidationError('Enter the verified provider outcome.')
    if not note.strip():
        raise ValidationError('Enter a verification note.')
    if decision in ('released','cancelled'):
        debit = CreditEntry.objects.filter(order=order, kind='purchase').first()
        maximum = -debit.amount if debit else Decimal('0.00')
        amount = maximum if decision=='released' else refund
        if not amount.is_finite() or amount!=amount.quantize(CENT) or not 0<=amount<=maximum:
            raise ValidationError('Refunds cannot exceed the credits charged for this order.')
        if amount:
            wallet = locked_wallet(debit.wallet_id)
            wallet.balance += amount
            wallet.save(update_fields=['balance'])
            CreditEntry.objects.create(wallet=wallet, actor=actor, order=order, kind='release', amount=amount, note=note)
    order.status = decision
    order.provider_reference = reference or order.provider_reference
    order.save(update_fields=['status','provider_reference'])
    ServiceOffer.objects.filter(pk=order.offer_id).update(payload='')
    from .models import Audit
    Audit.objects.create(actor=actor, action='service_'+decision, target=str(order.pk), detail=note)


def purge_expired_offers():
    cutoff=timezone.now()
    ServiceOffer.objects.filter(expires__lt=cutoff,serviceorder__isnull=True).delete()
    ServiceOffer.objects.filter(expires__lt=cutoff).exclude(payload='').update(payload='')
