from __future__ import annotations

from .access_control import is_platform_admin
from .ai_feature_rollout import feature_enabled
from .business_mapping_access_service import authorized_account_codes, authorized_minesite_names
from .platform_roles import active_profile, explicit_roles, has_business_role


BUSINESS_OVERVIEW_READ_PERMISSIONS = {
    "view_business_review", "view_business_review_financials", "view_business_review_fleet",
    "view_business_command_center", "view_country_revenue", "view_customer_revenue",
    "view_key_account_revenue", "view_business_line_revenue", "view_business_data_confidence",
    "view_business_review_data_confidence", "compare_business_entities", "compare_business_periods",
}


def business_review_enabled(user) -> bool:
    if not user or not user.is_authenticated or not feature_enabled("ENABLE_BUSINESS_REVIEW", user):
        return False
    if explicit_roles(active_profile(user)) is not None:
        return has_business_role(user, "business_overview")
    return is_platform_admin(user) or user.has_perm("reports.view_business_review")


def has_business_review_permission(user, codename: str) -> bool:
    if not business_review_enabled(user):
        return False
    return (is_platform_admin(user)
            or (explicit_roles(active_profile(user)) is not None
                and has_business_role(user, "business_overview")
                and codename in BUSINESS_OVERVIEW_READ_PERMISSIONS)
            or user.has_perm(f"reports.{codename}"))


def filter_published_rows(rows: list[dict], user) -> list[dict]:
    """Apply the same Account and MineSite scope to every executive component."""
    sites = authorized_minesite_names(user)
    accounts = authorized_account_codes(user)
    normalized_sites = None if sites is None else {value.casefold() for value in sites}
    filtered = []
    for row in rows:
        row_sites = {
            str(value).casefold()
            for value in [row.get("minesite_name"), *(row.get("minesite_names") or [])]
            if value
        }
        site_allowed = normalized_sites is None or bool(row_sites & normalized_sites)
        source_codes = {str(value).casefold() for value in row.get("source_account_codes", [])}
        account_allowed = accounts is None or bool(source_codes & accounts) or str(row.get("account_code") or "").casefold() in accounts
        if site_allowed and account_allowed:
            filtered.append(row)
    return filtered
