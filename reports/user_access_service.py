from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import transaction
from django.db.models import Q

from .active_directory_service import (
    DirectoryIdentity,
    active_directory_integration,
    find_directory_identity,
    identity_is_allowed,
    synchronize_identity,
)
from .business_performance_service import BusinessPerformanceService
from .models import PlatformUser, UserAccessAuditLog
from .powerbi import RLS_ROLE_OPTIONS


PLATFORM_ROLE_FIELDS = {
    "admin": "is_platform_admin",
    "reporting": "can_access_reporting",
    "ai": "can_access_ai",
    "data": "can_access_data",
    "sources": "can_access_sources",
}
PLATFORM_ROLE_LABELS = {
    "admin": ("Admin", "Full platform administration."),
    "reporting": ("Reporting", "Access Power BI reports and reporting features."),
    "ai": ("AI", "Use Mining 360 AI and agent features."),
    "data": ("Data", "Access data-quality and analytical data modules."),
    "sources": ("Data Source", "Manage data sources and integrations."),
}
BP_ROLE_VALUES = {value for value, _ in PlatformUser.BUSINESS_PERFORMANCE_ROLES}


class UserAccessValidationError(ValueError):
    def __init__(self, message: str, *, field: str = ""):
        super().__init__(message)
        self.field = field


def _roles(item: PlatformUser) -> list[str]:
    return [code for code, field in PLATFORM_ROLE_FIELDS.items() if bool(getattr(item, field))]


def _scope_values(item: PlatformUser, key: str) -> list[str]:
    raw = (item.business_performance_scope or {}).get(key) or []
    values = raw if isinstance(raw, list) else [raw]
    return [str(value).strip() for value in values if str(value).strip()]


def access_source(item: PlatformUser) -> str:
    if item.auth_source == "active_directory" and item.directory_roles_managed:
        return "ad_groups"
    return "manual"


def access_snapshot(item: PlatformUser) -> dict:
    return {
        "active": item.is_active,
        "platform_roles": _roles(item),
        "directory_roles_managed": item.directory_roles_managed,
        "business_performance_access": item.business_performance_role,
        "countries": _scope_values(item, "country"),
        "customers": _scope_values(item, "customer"),
        "powerbi_rls_role": str((item.business_performance_scope or {}).get("rls_role") or ""),
    }


def serialize_user(item: PlatformUser, *, detail: bool = False) -> dict:
    roles = _roles(item)
    source = access_source(item)
    countries = _scope_values(item, "country")
    customers = _scope_values(item, "customer")
    payload = {
        "id": item.pk,
        "display_name": item.display_name,
        "upn": item.user_principal_name,
        "email": item.email or item.user_principal_name,
        "directory_username": item.directory_username,
        "auth_source": item.auth_source,
        "status": "active" if item.is_active else "disabled",
        "platform_roles": roles,
        "ad_managed_roles": roles if source == "ad_groups" else [],
        "manual_platform_roles": [] if source == "ad_groups" else roles,
        "directory_roles_managed": item.directory_roles_managed,
        "business_performance_access": item.business_performance_role,
        "countries": countries,
        "customers": customers,
        "powerbi_rls_role": str((item.business_performance_scope or {}).get("rls_role") or ""),
        "access_source": source,
        "updated_at": item.updated_at.isoformat(),
    }
    if detail:
        payload.update({
            "directory_groups": item.directory_groups_json or [],
            "created_at": item.created_at.isoformat(),
            "last_directory_sync_at": item.last_directory_sync_at.isoformat() if item.last_directory_sync_at else None,
        })
    return payload


def authorized_users_queryset(params):
    queryset = PlatformUser.objects.select_related("django_user").all()
    query = str(params.get("q") or "").strip()
    if query:
        queryset = queryset.filter(
            Q(display_name__icontains=query)
            | Q(user_principal_name__icontains=query)
            | Q(email__icontains=query)
            | Q(directory_username__icontains=query)
        )
    status = str(params.get("status") or "").strip()
    if status == "active":
        queryset = queryset.filter(is_active=True)
    elif status == "disabled":
        queryset = queryset.filter(is_active=False)
    role = str(params.get("role") or "").strip()
    if role in PLATFORM_ROLE_FIELDS:
        queryset = queryset.filter(**{PLATFORM_ROLE_FIELDS[role]: True})
    source = str(params.get("access_source") or "").strip()
    if source == "ad_groups":
        queryset = queryset.filter(auth_source="active_directory", directory_roles_managed=True)
    elif source == "manual":
        queryset = queryset.filter(directory_roles_managed=False)
    bp = str(params.get("business_performance") or "").strip()
    if bp == "none":
        queryset = queryset.filter(business_performance_role="")
    elif bp and bp in BP_ROLE_VALUES:
        queryset = queryset.filter(business_performance_role=bp)
    ordering = str(params.get("ordering") or "display_name")
    allowed_ordering = {"display_name", "-display_name", "updated_at", "-updated_at", "is_active", "-is_active", "business_performance_role", "-business_performance_role"}
    return queryset.order_by(ordering if ordering in allowed_ordering else "display_name", "pk")


def _distinct_existing_scope(key: str) -> list[str]:
    values = set()
    for scope in PlatformUser.objects.values_list("business_performance_scope", flat=True):
        raw = (scope or {}).get(key) or []
        for value in raw if isinstance(raw, list) else [raw]:
            if str(value).strip():
                values.add(str(value).strip())
    return sorted(values, key=str.casefold)


def _business_options(user) -> tuple[list[str], list[str], list[str]]:
    cache_key = "users-access:business-options:v1"
    cached = cache.get(cache_key)
    if cached:
        return cached["countries"], cached["customers"], cached.get("warnings", [])
    countries = _distinct_existing_scope("country")
    customers = _distinct_existing_scope("customer")
    warnings = []
    try:
        service = BusinessPerformanceService(user)
        live_countries = {str(value).strip() for value in service.filter_options("country", limit=1000) if str(value).strip()}
        live_customers = {str(value).strip() for value in service.filter_options("customer", limit=2000) if str(value).strip()}
        countries = sorted(live_countries | set(countries), key=str.casefold)
        customers = sorted(live_customers | set(customers), key=str.casefold)
    except Exception:
        warnings.append("Live Business Performance scope options are unavailable; configured values remain available.")
    payload = {"countries": countries, "customers": customers, "warnings": warnings}
    cache.set(cache_key, payload, 300)
    return countries, customers, warnings


def access_options(user) -> dict:
    countries, customers, warnings = _business_options(user)
    return {
        "platform_roles": [
            {"code": code, "label": label, "description": description}
            for code, (label, description) in PLATFORM_ROLE_LABELS.items()
        ],
        "business_performance_levels": [
            {"value": value, "label": label}
            for value, label in PlatformUser.BUSINESS_PERFORMANCE_ROLES
        ],
        "countries": [{"value": value, "label": value} for value in countries],
        "customers": [{"value": value, "label": value} for value in customers],
        "powerbi_rls_roles": [{"value": "", "label": "No RLS role"}] + [
            {"value": value, "label": value} for value in RLS_ROLE_OPTIONS
        ],
        "warnings": warnings,
    }


def _clean_list(value, field: str) -> list[str]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise UserAccessValidationError("Select values from the available options.", field=field)
    clean = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in clean:
            clean.append(text)
    return clean


def _validated_access(payload: dict, *, item: PlatformUser | None = None, actor=None) -> dict:
    roles = _clean_list(payload.get("platform_roles"), "platform_roles")
    unknown = sorted(set(roles) - set(PLATFORM_ROLE_FIELDS))
    if unknown:
        raise UserAccessValidationError(f"Unknown platform role: {', '.join(unknown)}.", field="platform_roles")
    if item and item.directory_roles_managed and payload.get("directory_roles_managed", True) and set(roles) != set(_roles(item)):
        raise UserAccessValidationError("Roles managed by Active Directory cannot be changed manually.", field="platform_roles")
    bp_role = str(payload.get("business_performance_access") or "").strip()
    if bp_role not in BP_ROLE_VALUES:
        raise UserAccessValidationError("Select a valid Business Performance access level.", field="business_performance_access")
    countries = _clean_list(payload.get("countries"), "countries")
    customers = _clean_list(payload.get("customers"), "customers")
    if actor is not None:
        allowed_countries, allowed_customers, _ = _business_options(actor)
        invalid_countries = sorted(set(countries) - set(allowed_countries), key=str.casefold)
        invalid_customers = sorted(set(customers) - set(allowed_customers), key=str.casefold)
        if invalid_countries:
            raise UserAccessValidationError("Select countries from the governed list.", field="countries")
        if invalid_customers:
            raise UserAccessValidationError("Select customers from the governed list.", field="customers")
    rls = str(payload.get("powerbi_rls_role") or "").strip()
    if rls and rls not in RLS_ROLE_OPTIONS:
        raise UserAccessValidationError("Select a configured Power BI RLS role.", field="powerbi_rls_role")
    if not bp_role and (countries or customers):
        raise UserAccessValidationError("Country and customer scopes require Business Performance access.", field="business_performance_access")
    return {
        "roles": roles, "bp_role": bp_role, "countries": countries,
        "customers": customers, "rls": rls,
        "directory_roles_managed": bool(payload.get("directory_roles_managed", False)),
    }


def _apply_access(item: PlatformUser, values: dict):
    administrator = "admin" in values["roles"]
    for code, field in PLATFORM_ROLE_FIELDS.items():
        setattr(item, field, administrator or code in values["roles"])
    item.directory_roles_managed = values["directory_roles_managed"] if item.auth_source == "active_directory" else False
    item.business_performance_role = "Administrator" if administrator else values["bp_role"]
    scope = {}
    if values["countries"]:
        scope["country"] = values["countries"]
    if values["customers"]:
        scope["customer"] = values["customers"]
    if values["rls"]:
        scope["rls_role"] = values["rls"]
    item.business_performance_scope = scope
    item.save()
    if item.django_user:
        item.django_user.is_staff = item.is_platform_admin
        item.django_user.is_superuser = item.is_platform_admin
        item.django_user.is_active = item.is_active
        item.django_user.save(update_fields=["is_staff", "is_superuser", "is_active"])


def _audit(item, actor, action: str, before: dict, after: dict, metadata=None):
    UserAccessAuditLog.objects.create(
        platform_user=item, actor=actor if getattr(actor, "is_authenticated", False) else None,
        action=action, before_json=before, after_json=after, metadata_json=metadata or {},
    )


@transaction.atomic
def add_directory_user(payload: dict, actor) -> PlatformUser:
    object_id = str(payload.get("directory_object_id") or "").strip()
    username = str(payload.get("directory_username") or "").strip()
    if not object_id or not username:
        raise UserAccessValidationError("Select a valid company-directory user.", field="directory_user")
    if PlatformUser.objects.filter(Q(directory_object_id=object_id) | Q(user_principal_name__iexact=str(payload.get("upn") or ""))).exists():
        raise UserAccessValidationError("This user is already authorized in Mining 360.", field="directory_user")
    integration = active_directory_integration()
    if not integration:
        raise UserAccessValidationError("Active Directory is not configured.")
    identity = find_directory_identity(integration, username)
    if identity.object_id != object_id:
        raise UserAccessValidationError("The directory identity changed. Search and select the user again.")
    if not identity_is_allowed(integration, identity):
        raise UserAccessValidationError("This directory account is disabled or excluded by policy.")
    values = _validated_access(payload, actor=actor)
    synchronize_identity(identity, integration)
    item = PlatformUser.objects.select_for_update().get(directory_object_id=identity.object_id)
    item.is_active = True
    _apply_access(item, values)
    after = access_snapshot(item)
    _audit(item, actor, "user_added", {}, after, {"directory_object_id": object_id})
    return item


@transaction.atomic
def update_user_access(item: PlatformUser, payload: dict, actor) -> PlatformUser:
    item = PlatformUser.objects.select_for_update().select_related("django_user").get(pk=item.pk)
    before = access_snapshot(item)
    values = _validated_access(payload, item=item, actor=actor)
    removing_admin = item.is_platform_admin and "admin" not in values["roles"]
    if removing_admin and PlatformUser.objects.filter(is_active=True, is_platform_admin=True).exclude(pk=item.pk).count() == 0:
        raise UserAccessValidationError("The final active administrator cannot lose the Admin role.", field="platform_roles")
    _apply_access(item, values)
    after = access_snapshot(item)
    _audit(item, actor, "access_changed", before, after)
    return item


@transaction.atomic
def set_user_status(item: PlatformUser, active: bool, actor) -> PlatformUser:
    item = PlatformUser.objects.select_for_update().select_related("django_user").get(pk=item.pk)
    before = access_snapshot(item)
    if not active:
        if item.django_user_id == getattr(actor, "pk", None):
            raise UserAccessValidationError("You cannot disable your own account.")
        if item.is_platform_admin and PlatformUser.objects.filter(is_active=True, is_platform_admin=True).exclude(pk=item.pk).count() == 0:
            raise UserAccessValidationError("The final active administrator cannot be disabled.")
    item.is_active = bool(active)
    item.save(update_fields=["is_active", "updated_at"])
    if item.django_user:
        item.django_user.is_active = item.is_active
        item.django_user.save(update_fields=["is_active"])
    after = access_snapshot(item)
    _audit(item, actor, "user_enabled" if active else "user_disabled", before, after)
    return item


def serialize_audit(item: UserAccessAuditLog) -> dict:
    return {
        "id": item.pk,
        "action": item.action,
        "action_label": item.get_action_display(),
        "actor": item.actor.get_full_name() or item.actor.username if item.actor else "System",
        "before": item.before_json,
        "after": item.after_json,
        "created_at": item.created_at.isoformat(),
    }
