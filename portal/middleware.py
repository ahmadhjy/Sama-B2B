from django.contrib.auth import logout
from django.shortcuts import redirect, render
from django.http import JsonResponse
from .accounting import AccountingUnavailable, check_company

class AccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

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
            if not user.profile_complete and request.path not in ('/profile/', '/logout/'):
                if request.path.startswith('/api/'):
                    return JsonResponse({'error': 'Complete your profile first.', 'profile_url': '/profile/'}, status=403)
                return redirect('/profile/?complete=1')
        response = self.get_response(request)
        if request.user.is_authenticated and not request.path.startswith('/static/'):
            response['Cache-Control'] = 'private, no-store'
        response['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'self'"
        response['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        return response
