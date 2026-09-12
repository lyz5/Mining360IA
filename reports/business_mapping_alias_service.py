from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from .business_mapping_access_service import filter_source_accounts_for_user, has_mapping_permission
from .business_mapping_country_scope import normalize_operating_country
from .business_mapping_normalization_service import normalize_business_name
from .business_mapping_validation_service import MappingValidationError
from .models import BusinessAccount, BusinessAccountAlias, MappingAuditLog, SourceAccountRecord


class BusinessAccountAliasService:
    def __init__(self, user):
        self.user = user

    def _require_edit(self):
        if not has_mapping_permission(self.user, "manage_business_accounts") and not has_mapping_permission(self.user, "edit_business_mapping"):
            raise MappingValidationError("You do not have permission to manage Account aliases.", code="PERMISSION_DENIED", status=403)

    def _authorized_account(self, account_id):
        allowed_ids = filter_source_accounts_for_user(
            SourceAccountRecord.objects.filter(active=True), self.user,
        ).exclude(canonical_account_id=None).values_list("canonical_account_id", flat=True)
        account = BusinessAccount.objects.filter(pk=account_id, active=True, pk__in=allowed_ids).first()
        if not account:
            raise MappingValidationError("Canonical Account not found in your authorized scope.", code="ACCOUNT_NOT_FOUND", status=404)
        return account

    def list(self, account_id):
        account = self._authorized_account(account_id)
        return account, list(account.aliases.filter(active=True).order_by("normalized_alias"))

    @transaction.atomic
    def create(self, account_id, alias):
        self._require_edit()
        account = self._authorized_account(account_id)
        alias = str(alias or "").strip()
        normalized = normalize_business_name(alias)
        if not normalized:
            raise MappingValidationError("Canonical Account name is required.", code="CANONICAL_NAME_REQUIRED")
        if normalized == account.normalized_account_name:
            raise MappingValidationError("This is already the Canonical Account name.", code="CANONICAL_NAME_UNCHANGED", status=409)

        previous_name = account.canonical_account_name
        previous_normalized = account.normalized_account_name
        promoted_aliases = BusinessAccountAlias.objects.filter(
            canonical_account=account, normalized_alias=normalized, active=True,
        ).first()
        if promoted_aliases:
            promoted_aliases.active = False
            promoted_aliases.save(update_fields=["active"])

        existing = BusinessAccountAlias.objects.filter(
            canonical_account=account,
            normalized_alias=previous_normalized,
            source_system="Canonical history",
        ).first()
        if existing:
            existing.alias = previous_name
            existing.active = True
            existing.validation_status = "Validated"
            existing.validated_by = self.user
            existing.validated_at = timezone.now()
            existing.save(update_fields=["alias", "active", "validation_status", "validated_by", "validated_at"])
            item = existing
        else:
            item = BusinessAccountAlias.objects.create(
                canonical_account=account,
                alias=previous_name,
                normalized_alias=previous_normalized,
                source_system="Canonical history",
                confidence=100,
                validation_status="Validated",
                validated_by=self.user,
                validated_at=timezone.now(),
            )
        account.canonical_account_name = alias
        account.normalized_account_name = normalized
        account.updated_by = self.user
        account.save(update_fields=["canonical_account_name", "normalized_account_name", "updated_by", "updated_at"])
        MappingAuditLog.objects.create(
            actor=self.user,
            action="Canonical Account renamed",
            entity_type="BusinessAccount",
            entity_id=str(account.pk),
            previous_value_json={"canonical_account_name": previous_name},
            new_value_json={"canonical_account_name": alias, "historical_alias_id": item.pk},
        )
        return item

    @transaction.atomic
    def archive(self, account_id, alias_id):
        self._require_edit()
        account = self._authorized_account(account_id)
        item = BusinessAccountAlias.objects.select_for_update().filter(
            pk=alias_id, canonical_account=account, active=True,
        ).first()
        if not item:
            raise MappingValidationError("Alias not found.", code="ALIAS_NOT_FOUND", status=404)
        item.active = False
        item.save(update_fields=["active"])
        MappingAuditLog.objects.create(
            actor=self.user,
            action="Canonical Account alias removed",
            entity_type="BusinessAccountAlias",
            entity_id=str(item.pk),
            previous_value_json={"business_account_id": str(account.id), "alias": item.alias},
        )
        return item


class BusinessAccountOperatingCountryService:
    def __init__(self, user):
        self.user = user

    def _require_edit(self):
        if not has_mapping_permission(self.user, "manage_business_accounts") and not has_mapping_permission(self.user, "edit_business_mapping"):
            raise MappingValidationError("You do not have permission to classify Canonical Accounts.", code="PERMISSION_DENIED", status=403)

    def _authorized_account(self, account_id, for_update=False):
        allowed_ids = filter_source_accounts_for_user(
            SourceAccountRecord.objects.filter(active=True), self.user,
        ).exclude(canonical_account_id=None).values_list("canonical_account_id", flat=True)
        queryset = BusinessAccount.objects.filter(pk=account_id, active=True, pk__in=allowed_ids)
        account = queryset.select_for_update().first() if for_update else queryset.first()
        if not account:
            raise MappingValidationError("Canonical Account not found in your authorized scope.", code="ACCOUNT_NOT_FOUND", status=404)
        return account

    @transaction.atomic
    def assign(self, account_id, country):
        self._require_edit()
        country = normalize_operating_country(country)
        if not country:
            raise MappingValidationError("Select a valid operating country.", code="OPERATING_COUNTRY_REQUIRED")
        account = self._authorized_account(account_id, for_update=True)
        previous = account.assigned_operating_country
        account.assigned_operating_country = country
        account.operating_country_assigned_by = self.user
        account.operating_country_assigned_at = timezone.now()
        account.updated_by = self.user
        account.save(update_fields=[
            "assigned_operating_country", "operating_country_assigned_by",
            "operating_country_assigned_at", "updated_by", "updated_at",
        ])
        MappingAuditLog.objects.create(
            actor=self.user,
            action="Canonical Account operating country assigned",
            entity_type="BusinessAccount",
            entity_id=str(account.pk),
            previous_value_json={"assigned_operating_country": previous},
            new_value_json={"assigned_operating_country": country},
        )
        return account

    @transaction.atomic
    def clear(self, account_id):
        self._require_edit()
        account = self._authorized_account(account_id, for_update=True)
        previous = account.assigned_operating_country
        account.assigned_operating_country = ""
        account.operating_country_assigned_by = None
        account.operating_country_assigned_at = None
        account.updated_by = self.user
        account.save(update_fields=[
            "assigned_operating_country", "operating_country_assigned_by",
            "operating_country_assigned_at", "updated_by", "updated_at",
        ])
        MappingAuditLog.objects.create(
            actor=self.user,
            action="Canonical Account operating country cleared",
            entity_type="BusinessAccount",
            entity_id=str(account.pk),
            previous_value_json={"assigned_operating_country": previous},
            new_value_json={"assigned_operating_country": ""},
        )
        return account
