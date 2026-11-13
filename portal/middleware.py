from django.contrib.auth import logout
from django.shortcuts import redirect, render
from django.http import JsonResponse
from .accounting import AccountingUnavailable, check_company
from .permissions import ai_requests_coming_soon

REQUEST_PAGES = {
    'new_request': 'New travel request', 'requests': 'Travel requests',
    'drafts_review': 'Trip drafts', 'request_detail': 'Travel request',
    'request_files': 'Travel documents', 'quick_approval': 'Travel approval',
    'travel_overview': 'Travel overview',
}
REQUEST_ACTIONS = {
    'draft_new', 'draft_archive', 'draft_save', 'draft_guide', 'draft_select',
    'provider_offers', 'provider_cities', 'assistant', 'request_updates',
    'request_export', 'request_edit', 'remind_approvers', 'request_message', 'claim',
    'status_change', 'quote_create', 'quote_approval', 'quote_download', 'travel_message',
}

class AccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def process_view(self, request, view_func, view_args, view_kwargs):
        if not ai_requests_coming_soon(request.user):
            return None
        name = request.resolver_match.url_name
        if name in REQUEST_PAGES and request.method in ('GET', 'HEAD'):
            title = 'My requests' if name == 'requests' and request.GET.get('scope') == 'mine' else REQUEST_PAGES[name]
            return render(request, 'portal/ai_coming_soon.html', {'page_title': title})
        if name in REQUEST_PAGES or name in REQUEST_ACTIONS:
            return JsonResponse({'error': 'AI travel requests are coming soon.'}, status=403)

    def __call__(self, request):
        public = request.path in ('/login/', '/logout/', '/health/', '/manifest.webmanifest', '/service-worker.js') or request.path.startswith('/static/')
        user = request.user
        if user.is_authenticated and not public:
            if user.company_id:
                try:
                    active = check_company(user.company)
                except AccountingUnavailable:
                    return render(request, 'portal/unavailable.html', status=503)
                changed = user.is_primary and request.session.get('accounting_version') != user.company.identity_version
                if not active or changed:
                    logout(request)
                    return redirect('login')
            if request.path != '/profile/' and not ai_requests_coming_soon(user) and not user.profile_complete:
                if request.path.startswith('/api/'):
                    return JsonResponse({'error': 'Complete your profile first.', 'profile_url': '/profile/'}, status=403)
                return redirect('/profile/?complete=1')
        response = self.get_response(request)
        if request.user.is_authenticated and not request.path.startswith('/static/'):
            response['Cache-Control'] = 'private, no-store'
        response['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'self'"
        response['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        return response
