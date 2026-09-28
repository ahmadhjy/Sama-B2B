from django.db.models import Q
from .models import TravelRequest, User

def is_ceo(user):
    return user.is_authenticated and user.is_active and user.role == User.Role.CEO and user.company_id is None

def can_create(user):
    return bool(user.company_id and user.role in (User.Role.OWNER, User.Role.REQUESTER))

def can_finance(user):
    return is_ceo(user) or user.role == User.Role.FINANCE and user.is_sama or bool(user.company_id and user.role in (User.Role.OWNER, User.Role.ACCOUNTANT))

def visible_requests(user):
    qs = TravelRequest.objects.select_related('company', 'requester', 'assignee')
    if is_ceo(user):
        return qs
    if user.is_sama:
        return qs.filter(assignee=user) if user.role == User.Role.SALES else qs.none()
    qs = qs.filter(company_id=user.company_id)
    if user.role == User.Role.OWNER:
        return qs
    return qs.filter(Q(requester=user) | Q(quotes__approvals__user=user)).distinct()

def can_work(user, req):
    return is_ceo(user) or user.is_sama and user.role == User.Role.SALES and req.assignee_id == user.id

def can_submit_quote(user, req):
    return bool(user.company_id == req.company_id and (user.id == req.requester_id or user.role == User.Role.OWNER))

def can_view_passport(user, owner, req=None):
    if is_ceo(user) or user.id == owner.id:
        return True
    if user.company_id and user.company_id == owner.company_id and user.role == User.Role.OWNER:
        return True
    if req:
        return can_work(user, req) and req.requester_id == owner.id
    return user.is_sama and user.role == User.Role.SALES and TravelRequest.objects.filter(assignee=user, requester=owner).exists()

def can_attachment(user, attachment):
    if attachment.passport_owner_id:
        return can_view_passport(user, attachment.passport_owner)
    if not attachment.request_id or not visible_requests(user).filter(pk=attachment.request_id).exists():
        return False
    if attachment.internal:
        return can_work(user, attachment.request)
    if attachment.sensitive:
        return can_work(user, attachment.request) or can_submit_quote(user, attachment.request)
    return True
