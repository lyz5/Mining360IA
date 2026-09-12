from __future__ import annotations

from django.db.models import Q

from .access_control import is_platform_admin
from .ai_feature_rollout import feature_enabled


def studio_enabled(user) -> bool:
    return bool(user and user.is_authenticated and feature_enabled("ENABLE_BUSINESS_MAPPING_STUDIO", user))


def has_mapping_permission(user, codename: str, *, allow_admin: bool = True) -> bool:
    if not studio_enabled(user):
        return False
    if allow_admin and is_platform_admin(user):
        return True
    return user.has_perm(f"reports.{codename}")


def authorized_minesite_names(user) -> set[str] | None:
    """Return None for unrestricted users, otherwise the governed MineSite scope."""
    if is_platform_admin(user):
        return None
    try:
        scope = user.platformuser.business_performance_scope or {}
    except Exception:
        scope = {}
    values = scope.get("minesites") or scope.get("sites")
    if values is None:
        return set()
    return {str(value).strip() for value in values if str(value).strip()}


def authorized_account_codes(user) -> set[str] | None:
    if is_platform_admin(user):
        return None
    try:
        scope = user.platformuser.business_performance_scope or {}
    except Exception:
        scope = {}
    values = scope.get("account_codes") or scope.get("accounts")
    if values is None:
        return None
    return {str(value).strip().casefold() for value in values if str(value).strip()}


def filter_minesites_for_user(queryset, user):
    names = authorized_minesite_names(user)
    if names is None:
        return queryset
    if not names:
        return queryset.none()
    condition = Q()
    for name in names:
        condition |= Q(canonical_minesite_name__iexact=name)
    return queryset.filter(condition)


def filter_source_accounts_for_user(queryset, user):
    from .models import FleetSourceSnapshot

    account_codes = authorized_account_codes(user)
    if account_codes is not None:
        condition = Q()
        for code in account_codes:
            condition |= Q(source_record_id__iexact=code) | Q(canonical_account__canonical_account_code__iexact=code)
        return queryset.filter(condition) if account_codes else queryset.none()
    sites = authorized_minesite_names(user)
    if sites is None:
        return queryset
    if not sites:
        return queryset.none()
    site_condition = Q()
    for name in sites:
        site_condition |= Q(minesite_name__iexact=name)
    customer_names = FleetSourceSnapshot.objects.filter(site_condition, active=True).exclude(normalized_customer="").values_list("normalized_customer", flat=True)
    mapping_condition = Q()
    for name in sites:
        mapping_condition |= Q(canonical_account__minesite_mappings__minesite__canonical_minesite_name__iexact=name)
    return queryset.filter(Q(normalized_account_name__in=customer_names) | mapping_condition).distinct()
