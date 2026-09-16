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
    """Govern canonical Accounts into country-scoped customer groups.

    The database model keeps its original name for migration compatibility. The
    user-facing concept is Customer Country Group.
    """

    UNASSIGNED_COUNTRY = "UNASSIGNED"
    AUTOMATIC_GROUP_DESCRIPTION = "Automatically created canonical Account group."

    def __init__(self, user):
        self.user = user

    def _require_edit(self):
        if not has_mapping_permission(self.user, "manage_business_accounts") and not has_mapping_permission(self.user, "edit_business_mapping"):
            raise MappingValidationError("You do not have permission to manage Customer Country Groups.", code="PERMISSION_DENIED", status=403)

    def _authorized_account_ids(self):
        return set(filter_source_accounts_for_user(
            SourceAccountRecord.objects.filter(active=True), self.user,
        ).exclude(canonical_account_id=None).values_list("canonical_account_id", flat=True))

    @classmethod
    def account_operating_country(cls, account):
        assigned = normalize_operating_country(account.assigned_operating_country)
        if assigned:
            return assigned
        inferred = {
            normalized
            for value in (account.operating_countries_json or [])
            if (normalized := normalize_operating_country(value))
        }
        return next(iter(inferred)) if len(inferred) == 1 else cls.UNASSIGNED_COUNTRY

    @classmethod
    def _singleton_name(cls, account, country):
        base = str(account.canonical_account_name or account.canonical_account_code).strip()
        normalized = normalize_business_name(base)
        duplicate = CountryAccount.objects.filter(
            active=True,
            country=country,
            normalized_country_account_name=normalized,
        ).exists()
        return f"{base} · {account.canonical_account_code}" if duplicate else base

    @classmethod
    def ensure_account_group(cls, account, actor=None, inherited_key_account_id=None):
        """Guarantee one active Customer Country Group for an Account."""
        country = cls.account_operating_country(account)
        current = CountryAccountMembership.objects.select_related("country_account").filter(
            business_account=account,
            active=True,
        ).first()
        if current and current.country_account.active and current.country_account.country == country:
            return current.country_account

        if current and inherited_key_account_id is None:
            inherited_key_account_id = KeyAccountCountryMembership.objects.filter(
                country_account=current.country_account,
                active=True,
                key_account__active=True,
            ).values_list("key_account_id", flat=True).first()

        now = timezone.now()
        if current:
            current.active = False
            current.removed_by = actor
            current.removed_at = now
            current.save(update_fields=["active", "removed_by", "removed_at"])

        name = cls._singleton_name(account, country)
        group = CountryAccount.objects.create(
            country_account_code=f"CCG-{uuid.uuid4().hex.upper()}",
            country_account_name=name,
            normalized_country_account_name=normalize_business_name(name),
            country=country,
            description=cls.AUTOMATIC_GROUP_DESCRIPTION,
            created_by=actor,
            updated_by=actor,
        )
        CountryAccountMembership.objects.create(
            country_account=group,
            business_account=account,
            created_by=actor,
        )
        if inherited_key_account_id:
            KeyAccountCountryMembership.objects.create(
                key_account_id=inherited_key_account_id,
                country_account=group,
                created_by=actor,
            )
        from .business_mapping_key_account_service import KeyAccountService
        KeyAccountService.synchronize_account_membership(account, actor=actor)
        if actor:
            MappingAuditLog.objects.create(
                actor=actor,
                action="Customer Country Group assigned",
                entity_type="CountryAccount",
                entity_id=str(group.id),
                new_value_json={
                    "customer_country_group": group.country_account_name,
                    "country": country,
                    "business_account_id": str(account.id),
                    "automatic": True,
                },
            )
        return group

    @classmethod
    def ensure_all_accounts_grouped(cls, actor=None, account_ids=None):
        queryset = BusinessAccount.objects.filter(active=True)
        if account_ids is not None:
            queryset = queryset.filter(pk__in=account_ids)
        for account in queryset.iterator():
            cls.ensure_account_group(account, actor=actor)

    @transaction.atomic
    def create(self, name, country, description=""):
        self._require_edit()
        name = str(name or "").strip()
        country = normalize_operating_country(country)
        normalized = normalize_business_name(name)
        if not normalized:
            raise MappingValidationError("Customer Country Group name is required.", code="COUNTRY_ACCOUNT_NAME_REQUIRED")
        if not country:
            raise MappingValidationError("Select a governed Neemba operating country.", code="COUNTRY_ACCOUNT_COUNTRY_REQUIRED")
        if CountryAccount.objects.filter(active=True, country__iexact=country, normalized_country_account_name=normalized).exists():
            raise MappingValidationError("An active Customer Country Group with this name already exists in the selected country.", code="DUPLICATE_COUNTRY_ACCOUNT", status=409)
        prefix = re.sub(r"[^A-Z0-9]+", "-", name.upper()).strip("-")[:100] or "CUSTOMER-GROUP"
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
            actor=self.user,
            action="Customer Country Group created",
            entity_type="CountryAccount",
            entity_id=str(item.id),
            new_value_json={"name": item.country_account_name, "country": item.country, "version": item.version},
        )
        return item

    @transaction.atomic
    def create_with_members(self, name, country, business_account_ids, description=""):
        item = self.create(name, country, description)
        return self.add_members(item.id, business_account_ids)

    def _locked(self, country_account_id, version=None):
        item = CountryAccount.objects.select_for_update().filter(pk=country_account_id, active=True).first()
        if not item:
            raise MappingValidationError("Customer Country Group not found.", code="COUNTRY_ACCOUNT_NOT_FOUND", status=404)
        if version is not None and int(version) != item.version:
            raise MappingValidationError("This Customer Country Group was modified by another user. Reload the latest version.", code="COUNTRY_ACCOUNT_VERSION_CONFLICT", status=409)
        return item

    @transaction.atomic
    def rename(self, country_account_id, name, version=None):
        self._require_edit()
        item = self._locked(country_account_id, version)
        name = str(name or "").strip()
        normalized = normalize_business_name(name)
        if not normalized:
            raise MappingValidationError("Customer Country Group name is required.", code="COUNTRY_ACCOUNT_NAME_REQUIRED")
        if CountryAccount.objects.filter(active=True, country__iexact=item.country, normalized_country_account_name=normalized).exclude(pk=item.pk).exists():
            raise MappingValidationError("An active Customer Country Group with this name already exists in this country.", code="DUPLICATE_COUNTRY_ACCOUNT", status=409)
        previous = {"name": item.country_account_name, "version": item.version}
        item.country_account_name = name
        item.normalized_country_account_name = normalized
        item.version += 1
        item.updated_by = self.user
        item.save(update_fields=["country_account_name", "normalized_country_account_name", "version", "updated_by", "updated_at"])
        MappingAuditLog.objects.create(actor=self.user, action="Customer Country Group renamed", entity_type="CountryAccount", entity_id=str(item.id), previous_value_json=previous, new_value_json={"name": name, "version": item.version})
        return item

    @transaction.atomic
    def archive(self, country_account_id, reason, version=None):
        self._require_edit()
        item = self._locked(country_account_id, version)
        reason = str(reason or "").strip()
        if not reason:
            raise MappingValidationError("A deletion reason is required.", code="COUNTRY_ACCOUNT_DELETE_REASON_REQUIRED")
        accounts = list(BusinessAccount.objects.filter(
            country_account_memberships__country_account=item,
            country_account_memberships__active=True,
        ).distinct())
        inherited_key_id = KeyAccountCountryMembership.objects.filter(
            country_account=item,
            active=True,
            key_account__active=True,
        ).values_list("key_account_id", flat=True).first()
        now = timezone.now()
        CountryAccountMembership.objects.filter(country_account=item, active=True).update(active=False, removed_by=self.user, removed_at=now)
        KeyAccountCountryMembership.objects.filter(country_account=item, active=True).update(active=False, removed_by=self.user, removed_at=now)
        item.active = False
        item.version += 1
        item.updated_by = self.user
        item.save(update_fields=["active", "version", "updated_by", "updated_at"])
        for account in accounts:
            self.ensure_account_group(account, actor=self.user, inherited_key_account_id=inherited_key_id)
        MappingAuditLog.objects.create(actor=self.user, action="Customer Country Group archived", entity_type="CountryAccount", entity_id=str(item.id), new_value_json={"active": False, "version": item.version}, reason=reason)
        return item

    @transaction.atomic
    def add_members(self, country_account_id, business_account_ids):
        self._require_edit()
        item = self._locked(country_account_id)
        requested_ids = {str(value) for value in (business_account_ids or []) if value}
        if not requested_ids:
            raise MappingValidationError("Select at least one Canonical Account.", code="COUNTRY_ACCOUNT_MEMBER_REQUIRED")
        if not requested_ids.issubset({str(value) for value in self._authorized_account_ids()}):
            raise MappingValidationError("One or more Canonical Accounts are outside your authorized scope.", code="ACCESS_RESTRICTED", status=403)
        accounts = list(BusinessAccount.objects.select_for_update().filter(pk__in=requested_ids, active=True))
        if len(accounts) != len(requested_ids):
            raise MappingValidationError("One or more Canonical Accounts were not found.", code="ACCOUNT_NOT_FOUND", status=404)
        invalid_country = next((account for account in accounts if self.account_operating_country(account) != item.country), None)
        if invalid_country:
            raise MappingValidationError(
                f"{invalid_country.canonical_account_name} does not belong to the {item.country} operating-country scope.",
                code="COUNTRY_ACCOUNT_COUNTRY_CONFLICT",
                status=409,
            )

        added = []
        now = timezone.now()
        for account in accounts:
            current_memberships = list(CountryAccountMembership.objects.select_for_update().select_related("country_account").filter(
                business_account=account,
                active=True,
            ))
            if any(membership.country_account_id == item.id for membership in current_memberships):
                raise MappingValidationError(
                    f"{account.canonical_account_name} is already assigned to this Customer Country Group.",
                    code="COUNTRY_ACCOUNT_ALREADY_ASSIGNED",
                    status=409,
                )
            assigned_business_group = next((
                membership for membership in current_memberships
                if membership.country_account.description != self.AUTOMATIC_GROUP_DESCRIPTION
                or membership.country_account.memberships.filter(active=True).exclude(business_account=account).exists()
            ), None)
            if assigned_business_group:
                raise MappingValidationError(
                    f"{account.canonical_account_name} is already assigned to {assigned_business_group.country_account.country_account_name}. Separate it before assigning another group.",
                    code="COUNTRY_ACCOUNT_ALREADY_GROUPED",
                    status=409,
                )
            previous_memberships = current_memberships
            for previous in previous_memberships:
                previous.active = False
                previous.removed_by = self.user
                previous.removed_at = now
                previous.save(update_fields=["active", "removed_by", "removed_at"])
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
            from .business_mapping_key_account_service import KeyAccountService
            KeyAccountService.synchronize_account_membership(account, actor=self.user)
            for previous in previous_memberships:
                old_group = previous.country_account
                if old_group.description == self.AUTOMATIC_GROUP_DESCRIPTION and not old_group.memberships.filter(active=True).exists():
                    KeyAccountCountryMembership.objects.filter(country_account=old_group, active=True).update(active=False, removed_by=self.user, removed_at=now)
                    old_group.active = False
                    old_group.updated_by = self.user
                    old_group.save(update_fields=["active", "updated_by", "updated_at"])
        if added:
            item.version += 1
            item.updated_by = self.user
            item.save(update_fields=["version", "updated_by", "updated_at"])
            MappingAuditLog.objects.create(actor=self.user, action="Customer Country Group members moved", entity_type="CountryAccount", entity_id=str(item.id), new_value_json={"business_account_ids": [str(account.id) for account in added], "version": item.version})
        return item

    @transaction.atomic
    def remove_members(self, country_account_id, business_account_ids):
        self._require_edit()
        item = self._locked(country_account_id)
        requested_ids = {str(value) for value in (business_account_ids or []) if value}
        if not requested_ids.issubset({str(value) for value in self._authorized_account_ids()}):
            raise MappingValidationError("One or more Canonical Accounts are outside your authorized scope.", code="ACCESS_RESTRICTED", status=403)
        memberships = list(CountryAccountMembership.objects.select_related("business_account").filter(
            country_account=item,
            business_account_id__in=requested_ids,
            active=True,
        ))
        now = timezone.now()
        for membership in memberships:
            inherited_key_id = KeyAccountCountryMembership.objects.filter(
                country_account=item,
                active=True,
                key_account__active=True,
            ).values_list("key_account_id", flat=True).first()
            membership.active = False
            membership.removed_by = self.user
            membership.removed_at = now
            membership.save(update_fields=["active", "removed_by", "removed_at"])
            self.ensure_account_group(
                membership.business_account,
                actor=self.user,
                inherited_key_account_id=inherited_key_id,
            )
        if memberships:
            item.version += 1
            item.updated_by = self.user
            item.save(update_fields=["version", "updated_by", "updated_at"])
            MappingAuditLog.objects.create(actor=self.user, action="Customer Country Group members separated", entity_type="CountryAccount", entity_id=str(item.id), previous_value_json={"business_account_ids": [str(member.business_account_id) for member in memberships]}, new_value_json={"version": item.version})
        return item
