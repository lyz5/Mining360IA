from __future__ import annotations


def is_mining360_super_administrator(user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    try:
        platform_user = user.platformuser
    except (AttributeError, user.__class__.platformuser.RelatedObjectDoesNotExist):
        return False
    return bool(platform_user.is_active and platform_user.is_platform_admin)
