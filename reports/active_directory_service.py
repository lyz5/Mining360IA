from __future__ import annotations

import re
import ssl
import uuid
from dataclasses import dataclass

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import ActiveDirectorySyncRun, PlatformUser, SystemIntegrationConfig
from .system_configuration_service import decrypt_secrets


class ActiveDirectoryError(RuntimeError):
    def __init__(self, message, *, code="directory_error"):
        super().__init__(message)
        self.code = code


@dataclass
class DirectoryIdentity:
    object_id: str
    username: str
    upn: str
    email: str
    display_name: str
    distinguished_name: str
    groups: list[str]
    disabled: bool


def active_directory_integration(*, require_authentication=False):
    queryset = SystemIntegrationConfig.objects.filter(integration_type="Active Directory", is_active=True)
    item = queryset.filter(is_default=True).first() or queryset.first()
    if not item:
        return None
    if require_authentication and not bool((item.settings_json or {}).get("authentication_enabled")):
        return None
    return item


def active_directory_login_enabled():
    return active_directory_integration(require_authentication=True) is not None


def _ldap3():
    try:
        import ldap3
        from ldap3.utils.conv import escape_filter_chars
    except ImportError as exc:
        raise ActiveDirectoryError("The ldap3 dependency is not installed.", code="dependency_missing") from exc
    return ldap3, escape_filter_chars


def _group_values(value):
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    values = []
    for block in re.split(r"[;\r\n]+", str(value or "")):
        block = block.strip()
        if not block:
            continue
        if "=" in block and "," in block:
            values.append(block)
        else:
            values.extend(part.strip() for part in block.split(",") if part.strip())
    return values


def _split_groups(value):
    return {
        _group_name_from_dn(item).casefold()
        for item in _group_values(value)
    }


def _group_name_from_dn(value):
    match = re.match(r"\s*CN=((?:\\.|[^,])+)", str(value or ""), re.I)
    if not match:
        return str(value or "").strip()
    return re.sub(r"\\([,=+<>#;\"\\])", r"\1", match.group(1)).strip()


def _first(value, default=""):
    if isinstance(value, (list, tuple)):
        return value[0] if value else default
    return value if value not in (None, "") else default


def _object_id(value):
    value = _first(value)
    if isinstance(value, bytes):
        if len(value) == 16:
            return str(uuid.UUID(bytes_le=value))
        return value.hex()
    return str(value or "").strip()


def _is_disabled(value):
    try:
        return bool(int(_first(value, 0)) & 2)
    except (TypeError, ValueError):
        return False


def _settings(item):
    values = dict(item.settings_json or {})
    values.update(decrypt_secrets(item))
    return values


def _server_and_connection(item, *, user=None, password=None):
    ldap3, _ = _ldap3()
    config = _settings(item)
    validate = ssl.CERT_REQUIRED if config.get("validate_certificate", True) else ssl.CERT_NONE
    tls = ldap3.Tls(validate=validate, ca_certs_file=str(config.get("ca_certificate_file") or "") or None)
    server = ldap3.Server(
        str(config.get("host") or "").strip(),
        port=int(config.get("port") or (636 if config.get("use_ssl", True) else 389)),
        use_ssl=bool(config.get("use_ssl", True)),
        tls=tls,
        connect_timeout=int(config.get("connect_timeout") or 10),
        get_info=ldap3.NONE,
    )
    bind_user = user if user is not None else config.get("bind_dn")
    bind_password = password if password is not None else config.get("bind_password")
    try:
        connection = ldap3.Connection(
            server, user=bind_user, password=bind_password, receive_timeout=int(config.get("connect_timeout") or 10),
            raise_exceptions=True, auto_referrals=False,
        )
        connection.open()
        if config.get("start_tls") and not config.get("use_ssl"):
            connection.start_tls()
        connection.bind()
        return connection
    except Exception as exc:
        detail = str(exc).casefold()
        if "doesn't match any name" in detail or "hostname" in detail and "match" in detail:
            message = "The LDAPS certificate does not match the configured Domain Controller host. Use the server FQDN shown in the certificate."
            code = "certificate_hostname_mismatch"
        elif "certificate verify failed" in detail or "certificate" in detail and "verify" in detail:
            message = "The LDAPS certificate is not trusted. Install or configure the corporate CA certificate."
            code = "certificate_untrusted"
        elif "invalidcredentials" in detail or "invalid credentials" in detail or "data 52e" in detail:
            message = "The technical account or password was rejected by Active Directory."
            code = "invalid_bind_credentials"
        elif "socket" in detail or "connection" in detail or "timed out" in detail:
            message = "The Domain Controller could not be reached on the configured LDAP port."
            code = "directory_unreachable"
        else:
            message = "Active Directory connection or technical-account bind failed."
            code = "bind_failed"
        raise ActiveDirectoryError(message, code=code) from exc


def _attributes(config):
    return list(dict.fromkeys([
        config.get("username_attribute") or "sAMAccountName",
        config.get("upn_attribute") or "userPrincipalName",
        config.get("email_attribute") or "mail",
        config.get("display_name_attribute") or "displayName",
        config.get("object_id_attribute") or "objectGUID",
        config.get("group_membership_attribute") or "memberOf",
        "userAccountControl",
    ]))


def _identity_from_values(distinguished_name, values, config):
    username_attr = config.get("username_attribute") or "sAMAccountName"
    upn_attr = config.get("upn_attribute") or "userPrincipalName"
    membership_attr = config.get("group_membership_attribute") or "memberOf"
    raw_groups = values.get(membership_attr) or []
    if not isinstance(raw_groups, (list, tuple)):
        raw_groups = [raw_groups]
    groups = sorted({_group_name_from_dn(value) for value in raw_groups if value})
    username = str(_first(values.get(username_attr)) or "").strip()
    upn = str(_first(values.get(upn_attr)) or "").strip().lower()
    return DirectoryIdentity(
        object_id=_object_id(values.get(config.get("object_id_attribute") or "objectGUID")),
        username=username,
        upn=upn,
        email=str(_first(values.get(config.get("email_attribute") or "mail")) or upn).strip().lower(),
        display_name=str(_first(values.get(config.get("display_name_attribute") or "displayName")) or username or upn).strip(),
        distinguished_name=str(distinguished_name or ""),
        groups=groups,
        disabled=_is_disabled(values.get("userAccountControl")),
    )


def _identity(entry, config):
    return _identity_from_values(entry.entry_dn, entry.entry_attributes_as_dict, config)


def _user_allowed(identity, config):
    allowed = _split_groups(config.get("allowed_groups"))
    return bool(allowed and allowed.intersection({group.casefold() for group in identity.groups}))


def identity_is_allowed(item, identity):
    config = _settings(item)
    allowed_groups = _split_groups(config.get("allowed_groups"))
    return not identity.disabled and (not allowed_groups or _user_allowed(identity, config))


def find_directory_identity(item, username):
    ldap3, escape_filter_chars = _ldap3()
    config = _settings(item)
    clean = str(username or "").strip()
    if not clean:
        raise ActiveDirectoryError("Username is required.", code="invalid_credentials")
    if "\\" in clean:
        clean = clean.rsplit("\\", 1)[-1]
    login_attr = config.get("username_attribute") or "sAMAccountName"
    upn_attr = config.get("upn_attribute") or "userPrincipalName"
    escaped = escape_filter_chars(clean)
    identity_filter = f"(|({login_attr}={escaped})({upn_attr}={escaped}))"
    base_filter = str(config.get("user_filter") or "(&(objectCategory=person)(objectClass=user))").strip()
    search_filter = f"(&{base_filter}{identity_filter})"
    connection = _server_and_connection(item)
    try:
        connection.search(
            search_base=str(config.get("user_search_base") or config.get("base_dn") or ""),
            search_filter=search_filter,
            search_scope=ldap3.SUBTREE,
            attributes=_attributes(config),
            size_limit=2,
        )
        if len(connection.entries) != 1:
            raise ActiveDirectoryError("The directory account was not found or is ambiguous.", code="user_not_found")
        return _identity(connection.entries[0], config)
    finally:
        connection.unbind()


def search_directory_identities(item, query, *, limit=20):
    ldap3, escape_filter_chars = _ldap3()
    config = _settings(item)
    clean = str(query or "").strip()
    if len(clean) < 2:
        return []
    escaped = escape_filter_chars(clean)
    username_attr = config.get("username_attribute") or "sAMAccountName"
    upn_attr = config.get("upn_attribute") or "userPrincipalName"
    email_attr = config.get("email_attribute") or "mail"
    display_attr = config.get("display_name_attribute") or "displayName"
    terms = f"(|({username_attr}=*{escaped}*)({upn_attr}=*{escaped}*)({email_attr}=*{escaped}*)({display_attr}=*{escaped}*))"
    base_filter = str(config.get("user_filter") or "(&(objectCategory=person)(objectClass=user))").strip()
    connection = _server_and_connection(item)
    try:
        connection.search(
            search_base=str(config.get("user_search_base") or config.get("base_dn") or ""),
            search_filter=f"(&{base_filter}{terms})",
            search_scope=ldap3.SUBTREE,
            attributes=_attributes(config),
            size_limit=min(50, max(1, int(limit))),
        )
        identities = [_identity(entry, config) for entry in connection.entries]
        allowed_groups = _split_groups(config.get("allowed_groups"))
        return [
            identity for identity in identities
            if not identity.disabled and (not allowed_groups or _user_allowed(identity, config))
        ]
    finally:
        connection.unbind()


def authenticate_directory_user(username, password):
    item = active_directory_integration(require_authentication=True)
    if not item or not password:
        return None
    config = _settings(item)
    identity = find_directory_identity(item, username)
    if identity.disabled:
        raise ActiveDirectoryError("This directory account is disabled.", code="account_disabled")
    allowed_groups = _split_groups(config.get("allowed_groups"))
    existing = PlatformUser.objects.filter(
        Q(directory_object_id=identity.object_id) | Q(user_principal_name__iexact=identity.upn),
        auth_source="active_directory",
        is_active=True,
    ).first()
    if allowed_groups and not _user_allowed(identity, config):
        raise ActiveDirectoryError("This account is not in an authorized Active Directory group.", code="group_not_allowed")
    if not allowed_groups and existing is None:
        raise ActiveDirectoryError(
            "This directory account has not been authorized in Mining 360.",
            code="not_synchronized",
        )
    connection = _server_and_connection(item, user=identity.distinguished_name, password=password)
    connection.unbind()
    if allowed_groups and not config.get("create_users_on_login", True):
        if not existing:
            raise ActiveDirectoryError("The directory account has not been synchronized with Mining 360.", code="not_synchronized")
    return synchronize_identity(identity, item)


def _access_from_groups(identity, config):
    groups = {value.casefold() for value in identity.groups}
    admin = bool(groups.intersection(_split_groups(config.get("admin_groups"))))
    return {
        "is_platform_admin": admin,
        "can_access_reporting": admin or bool(groups.intersection(_split_groups(config.get("reporting_groups")))),
        "can_access_ai": admin or bool(groups.intersection(_split_groups(config.get("ai_groups")))),
        "can_access_data": admin or bool(groups.intersection(_split_groups(config.get("data_groups")))),
        "can_access_sources": admin or bool(groups.intersection(_split_groups(config.get("sources_groups")))),
        "business_performance_role": "Administrator" if admin else str(config.get("default_business_performance_role") or "Viewer"),
    }


@transaction.atomic
def synchronize_identity(identity, item):
    config = _settings(item)
    if not identity.object_id or not identity.upn:
        raise ActiveDirectoryError("The directory entry must contain an immutable ID and userPrincipalName.", code="identity_incomplete")
    platform_user = PlatformUser.objects.filter(directory_object_id=identity.object_id).first()
    platform_user = platform_user or PlatformUser.objects.filter(user_principal_name__iexact=identity.upn).first()
    if platform_user and platform_user.auth_source not in {"active_directory", "local"} and platform_user.directory_object_id != identity.object_id:
        raise ActiveDirectoryError("The UPN is already linked to another identity provider.", code="identity_conflict")
    user = platform_user.django_user if platform_user else User.objects.filter(username__iexact=identity.upn).first()
    conflicting_user = User.objects.filter(username__iexact=identity.upn).exclude(pk=getattr(user, "pk", None)).first()
    if conflicting_user:
        raise ActiveDirectoryError("The directory UPN is already assigned to another Mining 360 account.", code="username_conflict")
    if user is None:
        user = User(username=identity.upn)
        user.set_unusable_password()
    access = _access_from_groups(identity, config)
    allowed_groups = _split_groups(config.get("allowed_groups"))
    active = not identity.disabled and (not allowed_groups or _user_allowed(identity, config))
    user.username = identity.upn
    user.email = identity.email or identity.upn
    user.first_name = identity.display_name[:150]
    user.set_unusable_password()
    user.is_active = active
    user.is_staff = access["is_platform_admin"]
    user.is_superuser = access["is_platform_admin"]
    user.save()
    access_defaults = access
    if platform_user and not platform_user.directory_roles_managed:
        access_defaults = {
            "is_platform_admin": platform_user.is_platform_admin,
            "can_access_reporting": platform_user.can_access_reporting,
            "can_access_ai": platform_user.can_access_ai,
            "can_access_data": platform_user.can_access_data,
            "can_access_sources": platform_user.can_access_sources,
            "business_performance_role": platform_user.business_performance_role,
        }
    defaults = {
        "azure_ad_id": f"ad:{identity.object_id}"[:128], "entra_tenant_id": "",
        "email": identity.email or identity.upn, "display_name": identity.display_name,
        "job_title": platform_user.job_title if platform_user else "", "is_active": active,
        "django_user": user, "auth_source": "active_directory", "directory_object_id": identity.object_id,
        "directory_username": identity.username, "directory_distinguished_name": identity.distinguished_name,
        "directory_groups_json": identity.groups, "last_directory_sync_at": timezone.now(), **access_defaults,
    }
    if platform_user:
        for key, value in defaults.items():
            setattr(platform_user, key, value)
        platform_user.user_principal_name = identity.upn
        platform_user.save()
    else:
        platform_user = PlatformUser.objects.create(user_principal_name=identity.upn, **defaults)
    return user


def directory_users(item):
    ldap3, _ = _ldap3()
    config = _settings(item)
    connection = _server_and_connection(item)
    try:
        maximum = int(config.get("maximum_sync_users") or 5000)
        results = connection.extend.standard.paged_search(
            search_base=str(config.get("user_search_base") or config.get("base_dn") or ""),
            search_filter=str(config.get("user_filter") or "(&(objectCategory=person)(objectClass=user))"),
            search_scope=ldap3.SUBTREE,
            attributes=_attributes(config),
            paged_size=min(500, maximum),
            size_limit=maximum,
            generator=False,
        )
        for result in results:
            if result.get("type") != "searchResEntry":
                continue
            yield _identity_from_values(result.get("dn"), result.get("attributes") or {}, config)
    finally:
        connection.unbind()


def synchronize_directory(item, *, user=None):
    run = ActiveDirectorySyncRun.objects.create(integration=item, created_by=user if getattr(user, "is_authenticated", False) else None)
    config = _settings(item)
    allowed_groups = _split_groups(config.get("allowed_groups"))
    seen = set()
    try:
        for identity in directory_users(item):
            run.discovered_users += 1
            if not identity.object_id or not identity.upn:
                run.skipped_users += 1
                continue
            seen.add(identity.object_id)
            existing = PlatformUser.objects.filter(Q(directory_object_id=identity.object_id) | Q(user_principal_name__iexact=identity.upn)).first()
            if not allowed_groups and existing is None:
                run.skipped_users += 1
                continue
            if allowed_groups and not _user_allowed(identity, config) and existing is None:
                run.skipped_users += 1
                continue
            try:
                synchronize_identity(identity, item)
                run.updated_users += int(existing is not None)
                run.created_users += int(existing is None)
            except ActiveDirectoryError:
                run.failed_users += 1
        if config.get("disable_missing_users") and seen:
            missing = PlatformUser.objects.filter(auth_source="active_directory").exclude(directory_object_id__in=seen)
            for platform_user in missing.select_related("django_user"):
                platform_user.is_active = False
                platform_user.save(update_fields=["is_active", "updated_at"])
                if platform_user.django_user:
                    platform_user.django_user.is_active = False
                    platform_user.django_user.save(update_fields=["is_active"])
                run.disabled_users += 1
        run.status = "Partially Completed" if run.failed_users else "Completed"
    except Exception as exc:
        run.status = "Failed"
        run.error_message = str(exc)[:2000]
    run.completed_at = timezone.now()
    run.save()
    return run


def test_active_directory_connection(item):
    ldap3, escape_filter_chars = _ldap3()
    config = _settings(item)
    raw_allowed_groups = _group_values(config.get("allowed_groups"))
    connection = _server_and_connection(item)
    try:
        base_filter = str(config.get("user_filter") or "(&(objectCategory=person)(objectClass=user))").strip()
        if not raw_allowed_groups:
            connection.search(
                search_base=str(config.get("user_search_base") or config.get("base_dn") or ""),
                search_filter=base_filter,
                search_scope=ldap3.SUBTREE,
                attributes=[config.get("username_attribute") or "sAMAccountName"],
                size_limit=5,
            )
            users_found = len(connection.entries)
            if not users_found:
                raise ActiveDirectoryError(
                    "The connection succeeded, but no user was found in the configured User Search Base.",
                    code="no_directory_users",
                )
            return {"users_found": users_found, "groups_found": 0, "access_mode": "manual"}
        group_dns = []
        group_names = []
        for value in raw_allowed_groups:
            # A comma is part of a full distinguished name. Simple group names
            # may still be separated with commas for backwards compatibility.
            if "=" in value and "," in value:
                group_dns.append(value)
            else:
                group_names.extend(part.strip() for part in value.split(",") if part.strip())
        if group_names:
            group_filter = "".join(f"(cn={escape_filter_chars(name)})" for name in group_names)
            connection.search(
                search_base=str(config.get("base_dn") or ""),
                search_filter=f"(&(objectCategory=group)(|{group_filter}))",
                search_scope=ldap3.SUBTREE,
                attributes=["cn"],
                size_limit=len(group_names) + 1,
            )
            resolved = {str(entry.entry_dn) for entry in connection.entries}
            resolved_names = {_group_name_from_dn(value).casefold() for value in resolved}
            missing = [name for name in group_names if name.casefold() not in resolved_names]
            if missing:
                raise ActiveDirectoryError(
                    f"Authorized Active Directory group(s) not found: {', '.join(missing)}.",
                    code="allowed_groups_not_found",
                )
            group_dns.extend(sorted(resolved))
        membership_attribute = config.get("group_membership_attribute") or "memberOf"
        membership_filter = "".join(
            f"({membership_attribute}={escape_filter_chars(group_dn)})"
            for group_dn in group_dns
        )
        if not membership_filter:
            raise ActiveDirectoryError("No authorized Active Directory group could be resolved.", code="allowed_groups_not_found")
        connection.search(
            search_base=str(config.get("user_search_base") or config.get("base_dn") or ""),
            search_filter=f"(&{base_filter}(|{membership_filter}))",
            search_scope=ldap3.SUBTREE,
            attributes=[config.get("username_attribute") or "sAMAccountName"],
            size_limit=5,
        )
        users_found = len(connection.entries)
        if not users_found:
            configured_names = ", ".join(sorted({_group_name_from_dn(value) for value in group_dns}))
            raise ActiveDirectoryError(
                "The connection succeeded, but no direct user member was found for the authorized "
                f"group(s): {configured_names}. Ask IT to verify the group's Member list and the configured User Search Base.",
                code="no_authorized_users",
            )
        return {"users_found": users_found, "groups_found": len(group_dns), "access_mode": "groups"}
    finally:
        connection.unbind()
