from __future__ import annotations

from functools import wraps

from django.http import JsonResponse
from django.shortcuts import redirect


def is_platform_admin(user):
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    profile = getattr(user, "platformuser", None)
    return bool(profile and profile.is_active and profile.is_platform_admin)


def can(user, permission: str, *, view_only=False):
    # Mining 360 exposes one platform-level Admin role. Deployment must honor
    # that role consistently instead of requiring a second, hidden set of
    # Django permissions that cannot be managed from Access Control.
    if is_platform_admin(user):
        return True
    if user.has_perm(f"deployment.{permission}"):
        return True
    return False


def deployment_permission(permission: str, *, view_only=False):
    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if can(request.user, permission, view_only=view_only):
                return view(request, *args, **kwargs)
            if "application/json" in request.headers.get("Accept", "") or request.path.startswith("/api/"):
                return JsonResponse({"ok": False, "error": "Deployment permission required."}, status=403)
            return redirect("dashboard")
        return wrapped
    return decorator
