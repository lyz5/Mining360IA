from __future__ import annotations

import re
import uuid

from django.db import transaction
from django.utils import timezone

from .business_mapping_access_service import filter_source_accounts_for_user, has_mapping_permission
from .business_mapping_normalization_service import normalize_business_name
from .business_mapping_validation_service import MappingValidationError
from .models import (
    BusinessAccount,
    CountryAccount,
    KeyAccount,
    KeyAccountCountryMembership,
    KeyAccountMembership,
    MappingAuditLog,
    SourceAccountRecord,
)


class KeyAccountService:
    def __init__(self, user):
        self.user = user

    def _require_edit(self):
        if not has_mapping_permission(self.user, "manage_business_accounts") and not has_mapping_permission(self.user, "edit_business_mapping"):
            raise MappingValidationError("You do not have permission to manage Key Accounts.", code="PERMISSION_DENIED", status=403)

    def _authorized_account_ids(self):
        return set(filter_source_accounts_for_user(
            SourceAccountRecord.objects.filter(active=True), self.user,
        ).exclude(canonical_account_id=None).values_list("canonical_account_id", flat=True))

    @transaction.atomic
    def create(self, name, description=""):
        self._require_edit()
        name = str(name or "").strip()
        normalized = normalize_business_name(name)
        if not normalized:
            raise MappingValidationError("Key Account name is required.", code="KEY_ACCOUNT_NAME_REQUIRED")
        if KeyAccount.objects.filter(active=True, normalized_key_account_name=normalized).exists():
            raise MappingValidationError("An active Key Account with this name already exists.", code="DUPLICATE_KEY_ACCOUNT", status=409)
        prefix = re.sub(r"[^A-Z0-9]+", "-", name.upper()).strip("-")[:120] or "KEY-ACCOUNT"
        item = KeyAccount.objects.create(
            key_account_code=f"{prefix}-{uuid.uuid4().hex[:8].upper()}",
            key_account_name=name,
            normalized_key_account_name=normalized,
            description=str(description or "").strip(),
            created_by=self.user,
            updated_by=self.user,
        )
        MappingAuditLog.objects.create(
            actor=self.user, action="Key Account created", entity_type="KeyAccount", entity_id=str(item.id),
            new_value_json={"name": item.key_account_name, "code": item.key_account_code, "version": item.version},
        )
        return item

    def _locked_key_account(self, key_account_id, version=None):
        item = KeyAccount.objects.select_for_update().filter(pk=key_account_id, active=True).first()
        if not item:
            raise MappingValidationError("Key Account not found.", code="KEY_ACCOUNT_NOT_FOUND", status=404)
        if version is not None and int(version) != item.version:
            raise MappingValidationError(
                "This Key Account was modified by another user. Reload the latest version.",
                code="KEY_ACCOUNT_VERSION_CONFLICT", status=409,
            )
        return item

    @transaction.atomic
    def rename(self, key_account_id, name, version=None):
        self._require_edit()
        item = self._locked_key_account(key_account_id, version)
        name = str(name or "").strip()
        normalized = normalize_business_name(name)
        if not normalized:
            raise MappingValidationError("Key Account name is required.", code="KEY_ACCOUNT_NAME_REQUIRED")
        if KeyAccount.objects.filter(active=True, normalized_key_account_name=normalized).exclude(pk=item.pk).exists():
            raise MappingValidationError("An active Key Account with this name already exists.", code="DUPLICATE_KEY_ACCOUNT", status=409)
        previous = {"name": item.key_account_name, "version": item.version}
        item.key_account_name = name
        item.normalized_key_account_name = normalized
        item.version += 1
        item.updated_by = self.user
        item.save(update_fields=["key_account_name", "normalized_key_account_name", "version", "updated_by", "updated_at"])
        MappingAuditLog.objects.create(
            actor=self.user, action="Key Account renamed", entity_type="KeyAccount", entity_id=str(item.id),
            previous_value_json=previous, new_value_json={"name": item.key_account_name, "version": item.version},
        )
        return item

    @transaction.atomic
    def archive(self, key_account_id, reason, version=None):
        self._require_edit()
        item = self._locked_key_account(key_account_id, version)
        reason = str(reason or "").strip()
        if not reason:
            raise MappingValidationError("A deletion reason is required.", code="KEY_ACCOUNT_DELETE_REASON_REQUIRED")
        now = timezone.now()
        memberships = list(KeyAccountMembership.objects.filter(key_account=item, active=True))
        country_memberships = list(KeyAccountCountryMembership.objects.filter(key_account=item, active=True))
        for membership in memberships:
            membership.active = False
            membership.removed_by = self.user
            membership.removed_at = now
            membership.save(update_fields=["active", "removed_by", "removed_at"])
        for membership in country_memberships:
            membership.active = False
            membership.removed_by = self.user
            membership.removed_at = now
            membership.save(update_fields=["active", "removed_by", "removed_at"])
        previous = {
            "name": item.key_account_name, "version": item.version,
            "business_account_ids": [str(membership.business_account_id) for membership in memberships],
        }
        item.active = False
        item.version += 1
        item.updated_by = self.user
        item.save(update_fields=["active", "version", "updated_by", "updated_at"])
        MappingAuditLog.objects.create(
            actor=self.user, action="Key Account archived", entity_type="KeyAccount", entity_id=str(item.id),
            previous_value_json=previous, new_value_json={"active": False, "version": item.version}, reason=reason,
        )
        return item

    @transaction.atomic
    def add_country_members(self, key_account_id, country_account_ids):
        self._require_edit()
        key_account = self._locked_key_account(key_account_id)
        requested_ids = {str(value) for value in (country_account_ids or []) if value}
        if not requested_ids:
            raise MappingValidationError("Select at least one Country Account.", code="KEY_ACCOUNT_COUNTRY_MEMBER_REQUIRED")
        country_accounts = list(CountryAccount.objects.filter(pk__in=requested_ids, active=True))
        if len(country_accounts) != len(requested_ids):
            raise MappingValidationError("One or more Country Accounts were not found.", code="COUNTRY_ACCOUNT_NOT_FOUND", status=404)
        authorized_ids = {str(value) for value in self._authorized_account_ids()}
        visible_ids = {
            str(item.pk) for item in country_accounts
            if item.memberships.filter(active=True, business_account_id__in=authorized_ids).exists() or item.created_by_id == getattr(self.user, "pk", None)
        }
        if visible_ids != requested_ids:
            raise MappingValidationError("One or more Country Accounts are outside your authorized scope.", code="ACCESS_RESTRICTED", status=403)
        conflict = KeyAccountCountryMembership.objects.filter(country_account_id__in=requested_ids, active=True).exclude(key_account=key_account).select_related("key_account", "country_account").first()
        if conflict:
            raise MappingValidationError(f"{conflict.country_account.country_account_name} already belongs to {conflict.key_account.key_account_name}.", code="KEY_ACCOUNT_COUNTRY_MEMBERSHIP_CONFLICT", status=409)
        added = []
        for country_account in country_accounts:
            membership = KeyAccountCountryMembership.objects.filter(key_account=key_account, country_account=country_account).first()
            if membership:
                if not membership.active:
                    membership.active = True
                    membership.removed_by = None
                    membership.removed_at = None
                    membership.created_by = self.user
                    membership.save(update_fields=["active", "removed_by", "removed_at", "created_by"])
                    added.append(country_account)
            else:
                KeyAccountCountryMembership.objects.create(key_account=key_account, country_account=country_account, created_by=self.user)
                added.append(country_account)
        if added:
            key_account.version += 1
            key_account.updated_by = self.user
            key_account.save(update_fields=["version", "updated_by", "updated_at"])
            MappingAuditLog.objects.create(actor=self.user, action="Key Account Country Accounts added", entity_type="KeyAccount", entity_id=str(key_account.id), new_value_json={"country_account_ids": [str(item.id) for item in added], "version": key_account.version})
        return key_account

    @transaction.atomic
    def remove_country_members(self, key_account_id, country_account_ids):
        self._require_edit()
        key_account = self._locked_key_account(key_account_id)
        requested_ids = {str(value) for value in (country_account_ids or []) if value}
        memberships = list(KeyAccountCountryMembership.objects.filter(key_account=key_account, country_account_id__in=requested_ids, active=True))
        now = timezone.now()
        for membership in memberships:
            membership.active = False
            membership.removed_by = self.user
            membership.removed_at = now
            membership.save(update_fields=["active", "removed_by", "removed_at"])
        if memberships:
            key_account.version += 1
            key_account.updated_by = self.user
            key_account.save(update_fields=["version", "updated_by", "updated_at"])
            MappingAuditLog.objects.create(actor=self.user, action="Key Account Country Accounts removed", entity_type="KeyAccount", entity_id=str(key_account.id), previous_value_json={"country_account_ids": [str(item.country_account_id) for item in memberships]}, new_value_json={"version": key_account.version})
        return key_account

    @transaction.atomic
    def add_members(self, key_account_id, business_account_ids):
        self._require_edit()
        key_account = KeyAccount.objects.select_for_update().filter(pk=key_account_id, active=True).first()
        if not key_account:
            raise MappingValidationError("Key Account not found.", code="KEY_ACCOUNT_NOT_FOUND", status=404)
        requested_ids = {str(value) for value in (business_account_ids or []) if value}
        if not requested_ids:
            raise MappingValidationError("Select at least one canonical Account.", code="KEY_ACCOUNT_MEMBER_REQUIRED")
        authorized_ids = {str(value) for value in self._authorized_account_ids()}
        if not requested_ids.issubset(authorized_ids):
            raise MappingValidationError("One or more canonical Accounts are outside your authorized scope.", code="ACCESS_RESTRICTED", status=403)
        accounts = list(BusinessAccount.objects.filter(pk__in=requested_ids, active=True))
        if len(accounts) != len(requested_ids):
            raise MappingValidationError("One or more canonical Accounts were not found.", code="ACCOUNT_NOT_FOUND", status=404)
        conflicts = KeyAccountMembership.objects.filter(
            business_account_id__in=requested_ids, active=True,
        ).exclude(key_account=key_account).select_related("key_account")
        if conflicts.exists():
            conflict = conflicts.first()
            raise MappingValidationError(
                f"{conflict.business_account.canonical_account_name} already belongs to {conflict.key_account.key_account_name}.",
                code="KEY_ACCOUNT_MEMBERSHIP_CONFLICT", status=409,
            )
        added = []
        for account in accounts:
            membership = KeyAccountMembership.objects.filter(key_account=key_account, business_account=account).first()
            if membership and not membership.active:
                membership.active = True
                membership.removed_at = None
                membership.removed_by = None
                membership.created_by = self.user
                membership.save(update_fields=["active", "removed_at", "removed_by", "created_by"])
                added.append(account)
            elif not membership:
                KeyAccountMembership.objects.create(key_account=key_account, business_account=account, created_by=self.user)
                added.append(account)
        if added:
            key_account.version += 1
            key_account.updated_by = self.user
            key_account.save(update_fields=["version", "updated_by", "updated_at"])
            MappingAuditLog.objects.create(
                actor=self.user, action="Key Account members added", entity_type="KeyAccount", entity_id=str(key_account.id),
                new_value_json={"business_account_ids": [str(item.id) for item in added], "version": key_account.version},
            )
        return key_account

    @transaction.atomic
    def remove_members(self, key_account_id, business_account_ids):
        self._require_edit()
        key_account = KeyAccount.objects.select_for_update().filter(pk=key_account_id, active=True).first()
        if not key_account:
            raise MappingValidationError("Key Account not found.", code="KEY_ACCOUNT_NOT_FOUND", status=404)
        requested_ids = {str(value) for value in (business_account_ids or []) if value}
        authorized_ids = {str(value) for value in self._authorized_account_ids()}
        if not requested_ids.issubset(authorized_ids):
            raise MappingValidationError("One or more canonical Accounts are outside your authorized scope.", code="ACCESS_RESTRICTED", status=403)
        memberships = list(KeyAccountMembership.objects.filter(
            key_account=key_account, business_account_id__in=requested_ids, active=True,
        ))
        now = timezone.now()
        for membership in memberships:
            membership.active = False
            membership.removed_by = self.user
            membership.removed_at = now
            membership.save(update_fields=["active", "removed_by", "removed_at"])
        if memberships:
            key_account.version += 1
            key_account.updated_by = self.user
            key_account.save(update_fields=["version", "updated_by", "updated_at"])
            MappingAuditLog.objects.create(
                actor=self.user, action="Key Account members removed", entity_type="KeyAccount", entity_id=str(key_account.id),
                previous_value_json={"business_account_ids": [str(item.business_account_id) for item in memberships]},
                new_value_json={"version": key_account.version},
            )
        return key_account
