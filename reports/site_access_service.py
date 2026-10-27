from __future__ import annotations

from dataclasses import dataclass

from .models import PlatformUser
from .powerbi import resolve_dataset_roles
from .platform_roles import explicit_roles


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
    if not profile or not profile.is_active or profile.is_platform_admin:
        return SiteAccessContext(False, (), "")
    roles = explicit_roles(profile)
    site_role = roles is not None and "site" in roles
    legacy_site_scope = profile.business_performance_role == SITE_ACCESS_ROLE
    if not site_role and not legacy_site_scope:
        return SiteAccessContext(False, (), "")
    raw_sites = (profile.business_performance_scope or {}).get("minesite") or []
    sites = raw_sites if isinstance(raw_sites, list) else [raw_sites]
    sites = tuple(str(site).strip() for site in sites if str(site).strip())
    if len(sites) != 1:
        raise SiteAccessDenied("The Site role requires exactly one authorized MineSite. Contact an administrator.")
    effective_username = str(
        profile.user_principal_name or profile.email or getattr(user, "email", "") or getattr(user, "username", "")
    ).strip()
    if not effective_username:
        raise SiteAccessDenied("The MineSite user does not have a valid effective identity.")
    return SiteAccessContext(True, sites, effective_username)


def site_role_enabled(user) -> bool:
    profile = _platform_user(user)
    roles = explicit_roles(profile)
    return bool(profile and profile.is_active and roles is not None and "site" in roles)


def site_report_role_map(user) -> dict[str, str]:
    profile = _platform_user(user)
    if not profile:
        return {}
    raw = (profile.business_performance_scope or {}).get("report_rls_roles")
    return {str(key): str(value).strip() for key, value in raw.items() if str(key).strip() and str(value).strip()} if isinstance(raw, dict) else {}


def site_report_allowed(user, report_id: str) -> bool:
    if not site_role_enabled(user):
        return True
    return bool(site_report_role_map(user).get(str(report_id or "")))


def filter_site_reports(user, reports):
    if not site_role_enabled(user):
        return list(reports)
    assigned = set(site_report_role_map(user))
    return [report for report in reports if str(getattr(report, "id", "")) in assigned]


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


def effective_report_security(user, dataset_name: str, fallback_role: str, *, report_id: str = "") -> dict:
    context = site_access_context(user)
    if not context.restricted:
        return {
            "restricted": False,
            "roles": [fallback_role] if fallback_role else [],
            "effective_username": "",
        }
    selected_role = ""
    if site_role_enabled(user):
        profile = _platform_user(user)
        mapping = site_report_role_map(user)
        configured_id = str(report_id or "").strip()
        if not configured_id:
            from .models import PowerBIReport
            candidate = PowerBIReport.objects.filter(is_active=True, report_name__iexact=dataset_name).order_by("id").first()
            configured_id = str(candidate.report_id) if candidate else ""
        selected_role = mapping.get(configured_id, "")
        if not selected_role or selected_role.casefold() == "global":
            raise SiteAccessDenied("This report has no assigned MineSite RLS role.")
    roles = resolve_dataset_roles(dataset_name, [selected_role] if selected_role else list(context.sites))
    if not roles:
        raise SiteAccessDenied("No Power BI RLS role is configured for this MineSite.")
    return {
        "restricted": True,
        "roles": roles,
        "effective_username": context.effective_username,
    }
