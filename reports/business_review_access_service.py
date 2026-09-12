from __future__ import annotations

from .access_control import is_platform_admin
from .ai_feature_rollout import feature_enabled
from .business_mapping_access_service import authorized_account_codes, authorized_minesite_names


def business_review_enabled(user) -> bool:
    if not user or not user.is_authenticated or not feature_enabled("ENABLE_BUSINESS_REVIEW", user):
        return False
    return is_platform_admin(user) or user.has_perm("reports.view_business_review")


def has_business_review_permission(user, codename: str) -> bool:
    if not business_review_enabled(user):
        return False
    return is_platform_admin(user) or user.has_perm(f"reports.{codename}")


def filter_published_rows(rows: list[dict], user) -> list[dict]:
    """Apply the same Account and MineSite scope to every executive component."""
    sites = authorized_minesite_names(user)
    accounts = authorized_account_codes(user)
    normalized_sites = None if sites is None else {value.casefold() for value in sites}
    filtered = []
    for row in rows:
        site_allowed = normalized_sites is None or str(row.get("minesite_name") or "").casefold() in normalized_sites
        source_codes = {str(value).casefold() for value in row.get("source_account_codes", [])}
        account_allowed = accounts is None or bool(source_codes & accounts) or str(row.get("account_code") or "").casefold() in accounts
        if site_allowed and account_allowed:
            filtered.append(row)
    return filtered
