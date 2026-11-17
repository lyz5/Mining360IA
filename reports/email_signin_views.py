from django.conf import settings
from django.contrib.auth import authenticate, login
from django.core.exceptions import ValidationError
from django.http import HttpResponseNotFound
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.utils.http import urlencode

from .email_signin_service import (
    SESSION_KEY, NONCE_KEY, SignInThrottled, request_code,
    EmailAccountNotRegistered, EmailAccountUnavailable,
)


def safe_next(request, value):
    return value if value and url_has_allowed_host_and_scheme(
        value, allowed_hosts={request.get_host()}, require_https=request.is_secure(),
    ) else reverse('dashboard')


@require_http_methods(['GET', 'POST'])
@never_cache
@sensitive_post_parameters('email', 'code')
def email_signin(request):
    if not getattr(settings, 'MINING360_EMAIL_CODE_LOGIN_ENABLED', False):
        return HttpResponseNotFound()
    destination = safe_next(request, request.POST.get('next') or request.GET.get('next'))
    if request.user.is_authenticated:
        return redirect(destination)
    context = {
        'next': destination, 'stage': 'code' if request.session.get(SESSION_KEY) else 'email',
        'email': str(request.POST.get('email') or '').strip()[:254],
    }
    from .email_signin_delivery import configuration_ready
    context['unavailable'] = not configuration_ready()
    if request.method == 'POST':
        if request.POST.get('action') == 'restart':
            request.session.pop(SESSION_KEY, None)
            request.session.pop(NONCE_KEY, None)
            return redirect(reverse('email-sign-in') + '?' + urlencode({'next': destination}))
        if context['unavailable']:
            context['error'] = 'Email sign-in is temporarily unavailable. Please use Windows sign-in.'
        elif request.POST.get('action') == 'verify':
            user = authenticate(request, email_code=request.POST.get('code', ''))
            if user:
                login(request, user)
                request.session.pop(SESSION_KEY, None)
                request.session.pop(NONCE_KEY, None)
                request.session.set_expiry(settings.MINING360_REMEMBER_SESSION_SECONDS if request.POST.get('remember') == 'on' else 0)
                return redirect(destination)
            context['error'] = 'The code is invalid or expired. Request another code if needed.'
            context['stage'] = 'code'
        else:
            try:
                request_code(request, request.POST.get('email'))
                return redirect(reverse('email-sign-in') + '?' + urlencode({'next': destination}))
            except ValidationError:
                context['error'] = 'Enter a valid email address.'
                context['stage'] = 'email'
            except EmailAccountNotRegistered:
                context['error'] = 'No Mining360 account is registered for this email address. Please contact your administrator.'
                context['stage'] = 'email'
            except EmailAccountUnavailable:
                context['error'] = 'This account is not enabled for email sign-in. Please contact your administrator.'
                context['stage'] = 'email'
            except SignInThrottled:
                context['error'] = 'Please wait before requesting another code.'
    response = render(request, 'reports/email_signin.html', context)
    response['Cache-Control'] = 'private, no-store'
    # Chromium form POSTs can send Origin:null under no-referrer, which Django
    # correctly rejects. Keep same-origin provenance and the normal CSRF checks.
    response['Referrer-Policy'] = 'same-origin'
    return response
