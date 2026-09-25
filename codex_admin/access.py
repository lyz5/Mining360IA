from functools import wraps

from django.conf import settings
from django.core.exceptions import PermissionDenied

from codex_integration.django_principal import is_mining360_super_administrator


def admin_access_allowed(user) -> bool:
    enabled = str(getattr(settings, "ENABLE_CODEX_ADMIN", "Disabled")).strip().casefold()
    return bool(
        enabled not in {"disabled", "false", "0", "off", ""}
        and getattr(user, "is_authenticated", False)
        and is_mining360_super_administrator(user)
    )


def codex_admin_access_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not admin_access_allowed(request.user):
            raise PermissionDenied("M360 AI Admin requires superuser access.")
        return view(request, *args, **kwargs)

    return wrapped
