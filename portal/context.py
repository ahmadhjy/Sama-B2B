from django.conf import settings
from .permissions import ai_requests_coming_soon, can_create, can_finance, is_ceo

def portal_context(request):
    user = request.user
    if not user.is_authenticated:
        return {'brand': 'HelloSama'}
    return {'brand': 'HelloSama', 'can_create': can_create(user), 'can_finance': can_finance(user),
            'ai_requests_coming_soon': ai_requests_coming_soon(user),
            'is_ceo': is_ceo(user), 'can_team': is_ceo(user) or user.role == 'owner',
            'unread_count': user.notifications.filter(read_at__isnull=True).count(),
            'push_available': bool(settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY)}
