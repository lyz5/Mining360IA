from __future__ import annotations

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from .access_control import is_platform_admin


def feature_enabled(setting_name: str, user=None) -> bool:
    mode = str(getattr(settings, setting_name, "Disabled") or "Disabled").strip().casefold()
    if mode in {"production", "enabled", "true", "1", "on"}:
        return True
    if mode in {"admin only", "admin_only", "admin"}:
        return bool(user and is_platform_admin(user))
    if mode in {"pilot", "pilot users", "pilot_users"}:
        if not user or not getattr(user, "is_authenticated", False):
            return False
        if is_platform_admin(user):
            return True
        from .models import FeaturePilotMembership

        now = timezone.now()
        return FeaturePilotMembership.objects.filter(
            feature_flag=setting_name,
            active=True,
        ).filter(
            Q(user=user) | Q(group__user=user),
        ).filter(
            Q(start_at__isnull=True) | Q(start_at__lte=now),
            Q(end_at__isnull=True) | Q(end_at__gte=now),
        ).exists()
    return False
