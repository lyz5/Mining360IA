from __future__ import annotations

import re
import uuid

from django.db import transaction
from django.utils import timezone

from .business_mapping_access_service import filter_source_accounts_for_user, has_mapping_permission
from .business_mapping_country_scope import normalize_operating_country
from .business_mapping_normalization_service import normalize_business_name
from .business_mapping_validation_service import MappingValidationError
from .models import (
    BusinessAccount,
    CountryAccount,
    CountryAccountMembership,
    KeyAccountCountryMembership,
    MappingAuditLog,
    SourceAccountRecord,
)


class CountryAccountService:
    def __init__(self, user):
        self.user = user

    def _require_edit(self):
        if not has_mapping_permission(self.user, "manage_business_accounts") and not has_mapping_permission(self.user, "edit_business_mapping"):
            raise MappingValidationError("You do not have permission to manage Country Accounts.", code="PERMISSION_DENIED", status=403)

    def _authorized_account_ids(self):
        return set(filter_source_accounts_for_user(
            SourceAccountRecord.objects.filter(active=True), self.user,
        ).exclude(canonical_account_id=None).values_list("canonical_account_id", flat=True))

    @transaction.atomic
    def create(self, name, country, description=""):
        self._require_edit()
        name = str(name or "").strip()
        country = normalize_operating_country(country)
        normalized = normalize_business_name(name)
        if not normalized:
            raise MappingValidationError("Country Account name is required.", code="COUNTRY_ACCOUNT_NAME_REQUIRED")
        if not country:
            raise MappingValidationError(
                "Select a governed Neemba operating country.",
                code="COUNTRY_ACCOUNT_COUNTRY_REQUIRED",
            )
        if CountryAccount.objects.filter(active=True, country__iexact=country, normalized_country_account_name=normalized).exists():
            raise MappingValidationError("An active Country Account with this name already exists in the selected country.", code="DUPLICATE_COUNTRY_ACCOUNT", status=409)
        prefix = re.sub(r"[^A-Z0-9]+", "-", name.upper()).strip("-")[:100] or "COUNTRY-ACCOUNT"
        item = CountryAccount.objects.create(
            country_account_code=f"{country}-{prefix}-{uuid.uuid4().hex[:8].upper()}",
            country_account_name=name,
            normalized_country_account_name=normalized,
            country=country,
            description=str(description or "").strip(),
            created_by=self.user,
            updated_by=self.user,
        )
        MappingAuditLog.objects.create(
            actor=self.user, action="Country Account created", entity_type="CountryAccount", entity_id=str(item.id),
            new_value_json={"name": item.country_account_name, "country": item.country, "version": item.version},
        )
        return item

    @transaction.atomic
    def create_with_members(self, name, country, business_account_ids, description=""):
        """Create a Country Account and assign its initial members as one commit."""
        item = self.create(name, country, description)
        return self.add_members(item.id, business_account_ids)

    def _locked(self, country_account_id, version=None):
        item = CountryAccount.objects.select_for_update().filter(pk=country_account_id, active=True).first()
        if not item:
            raise MappingValidationError("Country Account not found.", code="COUNTRY_ACCOUNT_NOT_FOUND", status=404)
        if version is not None and int(version) != item.version:
            raise MappingValidationError("This Country Account was modified by another user. Reload the latest version.", code="COUNTRY_ACCOUNT_VERSION_CONFLICT", status=409)
        return item

    @transaction.atomic
    def rename(self, country_account_id, name, version=None):
        self._require_edit()
        item = self._locked(country_account_id, version)
        name = str(name or "").strip()
        normalized = normalize_business_name(name)
        if not normalized:
            raise MappingValidationError("Country Account name is required.", code="COUNTRY_ACCOUNT_NAME_REQUIRED")
        if CountryAccount.objects.filter(active=True, country__iexact=item.country, normalized_country_account_name=normalized).exclude(pk=item.pk).exists():
            raise MappingValidationError("An active Country Account with this name already exists in this country.", code="DUPLICATE_COUNTRY_ACCOUNT", status=409)
        previous = {"name": item.country_account_name, "version": item.version}
        item.country_account_name = name
        item.normalized_country_account_name = normalized
        item.version += 1
        item.updated_by = self.user
        item.save(update_fields=["country_account_name", "normalized_country_account_name", "version", "updated_by", "updated_at"])
        MappingAuditLog.objects.create(actor=self.user, action="Country Account renamed", entity_type="CountryAccount", entity_id=str(item.id), previous_value_json=previous, new_value_json={"name": name, "version": item.version})
        return item

    @transaction.atomic
    def archive(self, country_account_id, reason, version=None):
        self._require_edit()
        item = self._locked(country_account_id, version)
        reason = str(reason or "").strip()
        if not reason:
            raise MappingValidationError("A deletion reason is required.", code="COUNTRY_ACCOUNT_DELETE_REASON_REQUIRED")
        now = timezone.now()
        CountryAccountMembership.objects.filter(country_account=item, active=True).update(active=False, removed_by=self.user, removed_at=now)
        KeyAccountCountryMembership.objects.filter(country_account=item, active=True).update(active=False, removed_by=self.user, removed_at=now)
        item.active = False
        item.version += 1
        item.updated_by = self.user
        item.save(update_fields=["active", "version", "updated_by", "updated_at"])
        MappingAuditLog.objects.create(actor=self.user, action="Country Account archived", entity_type="CountryAccount", entity_id=str(item.id), new_value_json={"active": False, "version": item.version}, reason=reason)
        return item

    @transaction.atomic
    def add_members(self, country_account_id, business_account_ids):
        self._require_edit()
        item = self._locked(country_account_id)
        requested_ids = {str(value) for value in (business_account_ids or []) if value}
        if not requested_ids:
            raise MappingValidationError("Select at least one canonical Account.", code="COUNTRY_ACCOUNT_MEMBER_REQUIRED")
        if not requested_ids.issubset({str(value) for value in self._authorized_account_ids()}):
            raise MappingValidationError("One or more canonical Accounts are outside your authorized scope.", code="ACCESS_RESTRICTED", status=403)
        accounts = list(BusinessAccount.objects.filter(pk__in=requested_ids, active=True))
        if len(accounts) != len(requested_ids):
            raise MappingValidationError("One or more canonical Accounts were not found.", code="ACCOUNT_NOT_FOUND", status=404)
        conflict = CountryAccountMembership.objects.filter(business_account_id__in=requested_ids, active=True).exclude(country_account=item).select_related("country_account", "business_account").first()
        if conflict:
            raise MappingValidationError(f"{conflict.business_account.canonical_account_name} already belongs to {conflict.country_account.country_account_name}.", code="COUNTRY_ACCOUNT_MEMBERSHIP_CONFLICT", status=409)
        added = []
        for account in accounts:
            membership = CountryAccountMembership.objects.filter(country_account=item, business_account=account).first()
            if membership:
                if not membership.active:
                    membership.active = True
                    membership.removed_by = None
                    membership.removed_at = None
                    membership.created_by = self.user
                    membership.save(update_fields=["active", "removed_by", "removed_at", "created_by"])
                    added.append(account)
            else:
                CountryAccountMembership.objects.create(country_account=item, business_account=account, created_by=self.user)
                added.append(account)
        if added:
            item.version += 1
            item.updated_by = self.user
            item.save(update_fields=["version", "updated_by", "updated_at"])
            MappingAuditLog.objects.create(actor=self.user, action="Country Account members added", entity_type="CountryAccount", entity_id=str(item.id), new_value_json={"business_account_ids": [str(account.id) for account in added], "version": item.version})
        return item

    @transaction.atomic
    def remove_members(self, country_account_id, business_account_ids):
        self._require_edit()
        item = self._locked(country_account_id)
        requested_ids = {str(value) for value in (business_account_ids or []) if value}
        if not requested_ids.issubset({str(value) for value in self._authorized_account_ids()}):
            raise MappingValidationError("One or more canonical Accounts are outside your authorized scope.", code="ACCESS_RESTRICTED", status=403)
        memberships = list(CountryAccountMembership.objects.filter(country_account=item, business_account_id__in=requested_ids, active=True))
        now = timezone.now()
        for membership in memberships:
            membership.active = False
            membership.removed_by = self.user
            membership.removed_at = now
            membership.save(update_fields=["active", "removed_by", "removed_at"])
        if memberships:
            item.version += 1
            item.updated_by = self.user
            item.save(update_fields=["version", "updated_by", "updated_at"])
            MappingAuditLog.objects.create(actor=self.user, action="Country Account members removed", entity_type="CountryAccount", entity_id=str(item.id), previous_value_json={"business_account_ids": [str(member.business_account_id) for member in memberships]}, new_value_json={"version": item.version})
        return item
