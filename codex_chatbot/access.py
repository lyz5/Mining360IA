from __future__ import annotations

from functools import wraps

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied

from codex_integration.django_principal import is_mining360_super_administrator

from .models import CodexChatbotPilot


def chatbot_access_allowed(user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    mode = str(getattr(settings, "ENABLE_CODEX_CHATBOT", "Disabled")).strip().casefold()
    if mode in {"disabled", "false", "0", "off", ""}:
        return False
    if is_mining360_super_administrator(user):
        return True
    if mode not in {"pilot", "pilot users", "pilot_users"}:
        return False
    return CodexChatbotPilot.objects.filter(user=user, active=True).exists()


def codex_chatbot_access_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not getattr(request.user, "is_authenticated", False):
            return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)
        if not chatbot_access_allowed(request.user):
            raise PermissionDenied("Codex Chatbot access is not enabled for this user.")
        return view(request, *args, **kwargs)

    return wrapped
