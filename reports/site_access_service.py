from __future__ import annotations

from dataclasses import dataclass

from .models import PlatformUser
from .powerbi import resolve_dataset_roles


SITE_ACCESS_ROLE = "MineSite"


class SiteAccessDenied(PermissionError):
    pass


@dataclass(frozen=True)
class SiteAccessContext:
    restricted: bool
    sites: tuple[str, ...]
    effective_username: str


def _platform_user(user) -> PlatformUser | None:
    if not user or not getattr(user, "is_authenticated", False):
        return None
    try:
        return user.platformuser
    except (AttributeError, PlatformUser.DoesNotExist):
        return None


def site_access_context(user) -> SiteAccessContext:
    profile = _platform_user(user)
    if not profile or profile.is_platform_admin or profile.business_performance_role != SITE_ACCESS_ROLE:
        return SiteAccessContext(False, (), "")
    raw_sites = (profile.business_performance_scope or {}).get("minesite") or []
    sites = raw_sites if isinstance(raw_sites, list) else [raw_sites]
    sites = tuple(str(site).strip() for site in sites if str(site).strip())
    if len(sites) != 1:
        raise SiteAccessDenied("The MineSite access scope is missing or invalid. Contact an administrator.")
    effective_username = str(
        profile.user_principal_name or profile.email or getattr(user, "email", "") or getattr(user, "username", "")
    ).strip()
    if not effective_username:
        raise SiteAccessDenied("The MineSite user does not have a valid effective identity.")
    return SiteAccessContext(True, sites, effective_username)


def enforce_intent_site_scope(intent: dict, user) -> dict:
    context = site_access_context(user)
    if not context.restricted:
        return intent
    filters = dict(intent.get("filters") or {})
    requested = filters.get("minesite") or filters.get("site")
    requested_values = requested if isinstance(requested, list) else ([requested] if requested else [])
    allowed = {site.casefold(): site for site in context.sites}
    if any(str(value).strip().casefold() not in allowed for value in requested_values):
        raise SiteAccessDenied("You do not have access to the requested MineSite.")
    filters.pop("site", None)
    filters["minesite"] = context.sites[0]
    return {**intent, "filters": filters}


def effective_report_security(user, dataset_name: str, fallback_role: str) -> dict:
    context = site_access_context(user)
    if not context.restricted:
        return {
            "restricted": False,
            "roles": [fallback_role] if fallback_role else [],
            "effective_username": "",
        }
    roles = resolve_dataset_roles(dataset_name, list(context.sites))
    if not roles:
        raise SiteAccessDenied("No Power BI RLS role is configured for this MineSite.")
    return {
        "restricted": True,
        "roles": roles,
        "effective_username": context.effective_username,
    }
