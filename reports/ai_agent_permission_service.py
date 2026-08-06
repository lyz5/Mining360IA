from __future__ import annotations

from .access_control import has_module_access, is_platform_admin


def agent_allowed(agent, user) -> bool:
    if not agent or not agent.active:
        return False
    if is_platform_admin(user):
        return True
    if not has_module_access(user, "ai"):
        return False
    try:
        config = agent.permission_config
    except Exception:
        return True
    if config.allowed_users.exists() and not config.allowed_users.filter(pk=user.pk).exists():
        return False
    if config.allowed_roles.exists() and not config.allowed_roles.filter(
        user__pk=user.pk
    ).exists():
        return False
    return True
