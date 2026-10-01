from __future__ import annotations

from functools import wraps

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.db import OperationalError
from django.http import JsonResponse
from .db_retry import sqlite_busy

from codex_integration.django_principal import is_mining360_super_administrator
from reports.access_control import has_module_access

from .models import CodexChatbotPilot


def chatbot_access_allowed(user) -> bool:
    if not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        return False
    mode = str(getattr(settings, "ENABLE_CODEX_CHATBOT", "Disabled")).strip().casefold()
    if mode in {"disabled", "false", "0", "off", ""}:
        return False
    if is_mining360_super_administrator(user):
        return True
    # Preserve access previously granted to Mining360 AI during consolidation.
    # Business tools still enforce their own Reporting/financial permissions.
    if has_module_access(user, "ai"):
        return True
    if mode not in {"pilot", "pilot users", "pilot_users"}:
        return False
    return CodexChatbotPilot.objects.filter(user=user, active=True).exists()


def codex_chatbot_access_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        api = request.path.startswith('/codex-chatbot/api/')
        if not getattr(request.user, "is_authenticated", False):
            if api:
                return JsonResponse({'ok': False, 'error': 'Your session has expired. Sign in again.', 'code': 'AUTH_REQUIRED'}, status=401)
            return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)
        if not chatbot_access_allowed(request.user):
            raise PermissionDenied("M360 Chatbot access is not enabled for this user.")
        try:
            return view(request, *args, **kwargs)
        except OperationalError as exc:
            if not api or not sqlite_busy(exc):
                raise
            response = JsonResponse({'ok': False, 'error': 'The local database is busy. Please try again shortly.', 'code': 'DATABASE_BUSY'}, status=503)
            response['Retry-After'] = '2'
            return response

    return wrapped
