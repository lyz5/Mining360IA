from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from .business_mapping_access_service import authorized_account_codes, authorized_minesite_names, has_mapping_permission
from .business_mapping_normalization_service import payload_hash
from .models import (
    AccountMineSiteCandidate,
    AccountMineSiteMapping,
    AccountMineSiteMappingVersion,
    BusinessAccount,
    MappingAuditLog,
    MappingEvidence,
    MappingIdempotencyRecord,
    MineSite,
    RevenueSiteAllocationRule,
)


class MappingValidationError(RuntimeError):
    def __init__(self, message: str, *, code: str = "VALIDATION_ERROR", status: int = 400, fields=None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.fields = fields or {}


def _parse_date(value, field: str, required: bool = False):
    if value in (None, ""):
        if required:
            raise MappingValidationError(f"{field} is required.", fields={field: "Required"})
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise MappingValidationError(f"{field} must use YYYY-MM-DD.", fields={field: "Invalid date"}) from exc


def _mapping_snapshot(mapping: AccountMineSiteMapping) -> dict:
    return {
        "id": str(mapping.id),
        "status": mapping.relationship_status,
        "version": mapping.current_version,
        "account": {"id": str(mapping.business_account_id), "name": mapping.business_account.canonical_account_name},
        "minesite": None if not mapping.minesite_id else {
            "id": str(mapping.minesite_id), "name": mapping.minesite.canonical_minesite_name,
        },
        "account_role": mapping.account_role,
        "is_primary_site": mapping.is_primary_site,
        "valid_from": mapping.valid_from.isoformat() if mapping.valid_from else None,
        "valid_to": mapping.valid_to.isoformat() if mapping.valid_to else None,
        "validated_by": mapping.updated_by.get_username() if mapping.updated_by else None,
        "validated_at": mapping.updated_at.isoformat(),
    }


@dataclass
class AccountMineSiteValidationService:
    user: object
    source_ip: str | None = None
    application_version: str = ""

    def _check_permission(self, codename="validate_business_mapping"):
        if not has_mapping_permission(self.user, codename):
            raise MappingValidationError(
                "You do not have permission to validate this mapping.",
                code="PERMISSION_DENIED",
                status=403,
            )

    def _idempotent_result(self, key: str, operation: str, digest: str):
        if not key:
            raise MappingValidationError("An idempotency key is required.", fields={"idempotency_key": "Required"})
        record = MappingIdempotencyRecord.objects.filter(user=self.user, idempotency_key=key).first()
        if not record:
            return None
        if record.operation != operation or record.payload_hash != digest:
            raise MappingValidationError("This idempotency key was already used for another request.", code="IDEMPOTENCY_CONFLICT", status=409)
        return record.response_json

    def save_draft(self, payload: dict) -> dict:
        self._check_permission("edit_business_mapping")
        operation = "save_draft"
        key = str(payload.get("idempotency_key") or "")
        digest = payload_hash({k: v for k, v in payload.items() if k != "idempotency_key"})
        previous = self._idempotent_result(key, operation, digest)
        if previous:
            return previous
        with transaction.atomic():
            mapping = self._load_or_create(payload, status="Draft")
            self._enforce_scope(mapping)
            expected = int(payload.get("version", mapping.current_version))
            if mapping.current_version != expected:
                raise MappingValidationError("This mapping was modified by another user.", code="STALE_VERSION", status=409)
            old = _mapping_snapshot(mapping)
            self._apply_payload(mapping, payload, require_complete=False)
            mapping.relationship_status = "Draft"
            mapping.current_version += 1
            mapping.updated_by = self.user
            mapping.save()
            version = self._create_version(mapping, payload, status="Draft")
            self._audit("Draft saved", mapping, old, _mapping_snapshot(mapping), str(payload.get("comment") or ""))
            response = {"ok": True, "mapping": _mapping_snapshot(mapping), "version_id": version.pk, "database_commit_confirmed": True}
            MappingIdempotencyRecord.objects.create(user=self.user, idempotency_key=key, operation=operation, payload_hash=digest, entity_id=str(mapping.id), response_json=response)
        return response

    def validate(self, payload: dict, mapping_id=None, *, no_site_required: bool = False) -> dict:
        self._check_permission()
        operation = "mark_no_site_required" if no_site_required else "validate_mapping"
        key = str(payload.get("idempotency_key") or "")
        digest = payload_hash({k: v for k, v in payload.items() if k != "idempotency_key"})
        previous = self._idempotent_result(key, operation, digest)
        if previous:
            return previous
        with transaction.atomic():
            if mapping_id:
                mapping = AccountMineSiteMapping.objects.select_for_update().select_related("business_account", "minesite").filter(pk=mapping_id).first()
                if not mapping:
                    raise MappingValidationError("Mapping not found.", code="NOT_FOUND", status=404)
            else:
                mapping = self._load_or_create(payload, status="Draft")
                mapping = AccountMineSiteMapping.objects.select_for_update().select_related("business_account", "minesite").get(pk=mapping.pk)
            self._enforce_scope(mapping)
            expected = int(payload.get("version", mapping.current_version))
            if expected != mapping.current_version:
                raise MappingValidationError("This mapping was modified by another user.", code="STALE_VERSION", status=409)
            old = _mapping_snapshot(mapping)
            self._apply_payload(mapping, payload, require_complete=not no_site_required)
            if no_site_required:
                reason = str(payload.get("no_site_reason") or "").strip()
                allowed = {"Head Office", "Regional Office", "Internal Account", "Non-Mining Customer", "Supplier", "Distributor", "Other"}
                if reason not in allowed:
                    raise MappingValidationError("Select a valid No MineSite Required reason.", fields={"no_site_reason": "Required"})
                mapping.minesite = None
                mapping.account_role = "No MineSite Required"
                mapping.no_site_reason = reason
                mapping.relationship_status = "No MineSite Required"
            else:
                self._validate_relationship(mapping)
                mapping.relationship_status = "Validated"
            mapping.current_version += 1
            mapping.active = True
            mapping.updated_by = self.user
            mapping.save()
            allocation_snapshot = self._save_allocation(mapping, payload.get("allocation") or {})
            mapping.revenue_allocation_status = allocation_snapshot.get("status", "Not Required" if not mapping.allocation_required else "Not Defined")
            mapping.save(update_fields=["revenue_allocation_status", "updated_at"])
            self._persist_evidence(mapping, payload)
            version = self._create_version(mapping, payload, status=mapping.relationship_status, allocation=allocation_snapshot)
            candidate_id = payload.get("candidate_id")
            if candidate_id:
                AccountMineSiteCandidate.objects.filter(pk=candidate_id).update(status="Selected", reviewed_by=self.user, reviewed_at=timezone.now())
            audit = self._audit("Mapping validated" if not no_site_required else "No MineSite Required decision", mapping, old, _mapping_snapshot(mapping), str(payload.get("comment") or ""))
            response = {
                "ok": True,
                "mapping": _mapping_snapshot(mapping),
                "mapping_version_id": version.pk,
                "audit_id": audit.pk,
                "warnings": [],
                "database_commit_confirmed": True,
            }
            MappingIdempotencyRecord.objects.create(user=self.user, idempotency_key=key, operation=operation, payload_hash=digest, entity_id=str(mapping.id), response_json=response)
        return response

    def archive(self, payload: dict, mapping_id) -> dict:
        self._check_permission("reject_business_mapping")
        operation = "archive_mapping"
        key = str(payload.get("idempotency_key") or "")
        digest = payload_hash({"mapping_id": str(mapping_id), **{k: v for k, v in payload.items() if k != "idempotency_key"}})
        previous = self._idempotent_result(key, operation, digest)
        if previous:
            return previous
        reason = str(payload.get("reason") or "").strip()
        if not reason:
            raise MappingValidationError("A removal reason is required.", fields={"reason": "Required"})
        with transaction.atomic():
            mapping = AccountMineSiteMapping.objects.select_for_update().select_related(
                "business_account", "minesite"
            ).filter(pk=mapping_id, active=True).first()
            if not mapping:
                raise MappingValidationError("Mapping not found.", code="NOT_FOUND", status=404)
            self._enforce_scope(mapping)
            expected = int(payload.get("version", mapping.current_version))
            if expected != mapping.current_version:
                raise MappingValidationError("This mapping was modified by another user.", code="STALE_VERSION", status=409)
            old = _mapping_snapshot(mapping)
            mapping.relationship_status = "Archived"
            mapping.active = False
            mapping.current_version += 1
            mapping.updated_by = self.user
            mapping.notes = reason
            mapping.save()
            RevenueSiteAllocationRule.objects.filter(
                business_account=mapping.business_account,
                minesite=mapping.minesite,
                status__in=["Validated", "Published"],
            ).update(status="Superseded")
            version = self._create_version(
                mapping, {"comment": reason}, status="Archived", allocation={"status": "Superseded"}
            )
            audit = self._audit("Mapping archived", mapping, old, _mapping_snapshot(mapping), reason)
            response = {
                "ok": True,
                "mapping": _mapping_snapshot(mapping),
                "mapping_version_id": version.pk,
                "audit_id": audit.pk,
                "database_commit_confirmed": True,
                "published_snapshot_unchanged": True,
            }
            MappingIdempotencyRecord.objects.create(
                user=self.user, idempotency_key=key, operation=operation, payload_hash=digest,
                entity_id=str(mapping.id), response_json=response,
            )
        return response

    def _load_or_create(self, payload, status):
        mapping_id = payload.get("mapping_id")
        if mapping_id:
            mapping = AccountMineSiteMapping.objects.select_for_update().select_related("business_account", "minesite").filter(pk=mapping_id).first()
            if not mapping:
                raise MappingValidationError("Mapping not found.", code="NOT_FOUND", status=404)
            return mapping
        account = BusinessAccount.objects.filter(pk=payload.get("business_account_id"), active=True).first()
        if not account:
            raise MappingValidationError("Select an active Business Account.", fields={"business_account_id": "Invalid"})
        account_scope = authorized_account_codes(self.user)
        if account_scope is not None and account.canonical_account_code.casefold() not in account_scope:
            raise MappingValidationError("You do not have permission to validate this mapping.", code="PERMISSION_DENIED", status=403)
        mapping = AccountMineSiteMapping.objects.create(
            business_account=account,
            account_role=str(payload.get("account_role") or "To Review"),
            relationship_status=status,
            current_version=0,
            created_by=self.user,
            updated_by=self.user,
        )
        return mapping

    def _enforce_scope(self, mapping):
        account_scope = authorized_account_codes(self.user)
        if account_scope is not None and mapping.business_account.canonical_account_code.casefold() not in account_scope:
            raise MappingValidationError("You do not have permission to validate this mapping.", code="PERMISSION_DENIED", status=403)
        site_scope = authorized_minesite_names(self.user)
        if mapping.minesite_id and site_scope is not None and mapping.minesite.canonical_minesite_name.casefold() not in {name.casefold() for name in site_scope}:
            raise MappingValidationError("You do not have permission to validate this mapping.", code="PERMISSION_DENIED", status=403)

    def _apply_payload(self, mapping, payload, require_complete):
        account_id = payload.get("business_account_id")
        if account_id and str(mapping.business_account_id) != str(account_id):
            raise MappingValidationError("The Business Account cannot be changed on this mapping.", fields={"business_account_id": "Conflict"})
        minesite_id = payload.get("minesite_id")
        if minesite_id:
            site = MineSite.objects.filter(pk=minesite_id, active=True).first()
            if not site:
                raise MappingValidationError("Select an active MineSite.", fields={"minesite_id": "Invalid"})
            site_scope = authorized_minesite_names(self.user)
            if site_scope is not None and site.canonical_minesite_name.casefold() not in {name.casefold() for name in site_scope}:
                raise MappingValidationError("You do not have permission to validate this mapping.", code="PERMISSION_DENIED", status=403)
            mapping.minesite = site
        elif require_complete:
            raise MappingValidationError("MineSite is required.", fields={"minesite_id": "Required"})
        role = str(payload.get("account_role") or mapping.account_role or "").strip()
        if role in {"", "Unknown", "To Review"}:
            role = "Mapped Account"
        valid_roles = {value for value, _ in AccountMineSiteMapping.ACCOUNT_ROLES}
        if role not in valid_roles or role in {"Unknown", "To Review", "No MineSite Required"} and require_complete:
            raise MappingValidationError("Select a valid Account role.", fields={"account_role": "Invalid"})
        mapping.account_role = role
        mapping.is_primary_site = bool(payload.get("is_primary_site", mapping.is_primary_site))
        mapping.valid_from = _parse_date(payload.get("valid_from"), "valid_from")
        mapping.valid_to = _parse_date(payload.get("valid_to"), "valid_to")
        if mapping.valid_from and mapping.valid_to and mapping.valid_to < mapping.valid_from:
            raise MappingValidationError("The effective end date cannot precede the start date.", fields={"valid_to": "Invalid"})
        mapping.allocation_required = bool((payload.get("allocation") or {}).get("required", False))
        mapping.mapping_method = str(payload.get("mapping_method") or "Manual")[:120]
        mapping.notes = str(payload.get("comment") or "")

    def _validate_relationship(self, mapping):
        overlaps = AccountMineSiteMapping.objects.select_for_update().filter(
            business_account=mapping.business_account,
            minesite=mapping.minesite,
            account_role=mapping.account_role,
            active=True,
            relationship_status__in=["Validated", "Published"],
        ).exclude(pk=mapping.pk)
        if mapping.valid_to:
            overlaps = overlaps.filter(Q(valid_from__isnull=True) | Q(valid_from__lte=mapping.valid_to))
        if mapping.valid_from:
            overlaps = overlaps.filter(Q(valid_to__isnull=True) | Q(valid_to__gte=mapping.valid_from))
        if overlaps.exists():
            raise MappingValidationError("An active mapping already exists for this Account, MineSite and role.", code="DUPLICATE_MAPPING", status=409)

    def _save_allocation(self, mapping, allocation):
        if not allocation or not allocation.get("required"):
            return {"status": "Not Required", "rules": []}
        try:
            percentage = Decimal(str(allocation.get("percentage")))
        except (InvalidOperation, TypeError):
            raise MappingValidationError("Enter a valid allocation percentage.", fields={"allocation.percentage": "Invalid"})
        if percentage < 0 or percentage > 100:
            raise MappingValidationError("Allocation percentage must be between 0 and 100.", fields={"allocation.percentage": "Invalid"})
        scope = {
            "business_account": mapping.business_account,
            "lob": str(allocation.get("lob") or ""),
            "division": str(allocation.get("division") or ""),
            "distribution_channel": str(allocation.get("distribution_channel") or ""),
            "company_code": str(allocation.get("company_code") or ""),
            "branch_code": str(allocation.get("branch_code") or ""),
        }
        active = RevenueSiteAllocationRule.objects.select_for_update().filter(
            **scope, status__in=["Validated", "Published"], valid_from__lte=mapping.valid_from,
        ).filter(Q(valid_to__isnull=True) | Q(valid_to__gte=mapping.valid_from))
        current_total = active.exclude(minesite=mapping.minesite).aggregate(value=Sum("allocation_percentage"))["value"] or Decimal("0")
        total = current_total + percentage
        if total > Decimal("100.0001"):
            raise MappingValidationError("The active allocation exceeds 100% for the selected scope.", code="ALLOCATION_EXCEEDS_100", fields={"allocation.percentage": "Total exceeds 100%"})
        rule, _ = RevenueSiteAllocationRule.objects.update_or_create(
            **scope,
            minesite=mapping.minesite,
            valid_from=mapping.valid_from,
            defaults={
                "allocation_method": str(allocation.get("method") or "Fixed percentage"),
                "allocation_percentage": percentage,
                "valid_to": mapping.valid_to,
                "status": "Validated",
                "validated_by": self.user,
                "validated_at": timezone.now(),
            },
        )
        status = "Defined" if abs(total - Decimal("100")) <= Decimal("0.0001") else "Partial"
        return {"status": status, "rules": [{"id": str(rule.id), "percentage": str(percentage)}], "total": str(total)}

    def _persist_evidence(self, mapping, payload):
        ids = payload.get("evidence_ids") or []
        candidate_id = payload.get("candidate_id")
        if ids and candidate_id:
            source = MappingEvidence.objects.filter(pk__in=ids, candidate_id=candidate_id, active=True)
            for item in source:
                MappingEvidence.objects.create(
                    mapping=mapping, evidence_type=item.evidence_type, source_system=item.source_system,
                    source_record_id=item.source_record_id, description=item.description, value=item.value,
                    weight=item.weight, supports_mapping=item.supports_mapping,
                )
        comment = str(payload.get("comment") or "").strip()
        if comment:
            MappingEvidence.objects.create(mapping=mapping, evidence_type="Business confirmation", description=comment, value=comment, weight=100)

    def _create_version(self, mapping, payload, status, allocation=None):
        previous = mapping.versions.order_by("-version_number").first()
        return AccountMineSiteMappingVersion.objects.create(
            mapping=mapping,
            version_number=mapping.current_version,
            account_snapshot_json={"id": str(mapping.business_account_id), "code": mapping.business_account.canonical_account_code, "name": mapping.business_account.canonical_account_name},
            minesite_snapshot_json={} if not mapping.minesite_id else {"id": str(mapping.minesite_id), "code": mapping.minesite.minesite_code, "name": mapping.minesite.canonical_minesite_name},
            role=mapping.account_role,
            allocation_snapshot_json=allocation or {},
            evidence_snapshot_json=[{
                "evidence_type": item.evidence_type,
                "description": item.description,
                "source_system": item.source_system,
                "source_record_id": item.source_record_id,
                "weight": str(item.weight),
            } for item in mapping.evidence.all()],
            status=status,
            change_reason=str(payload.get("comment") or ""),
            created_by=self.user,
            validated_by=self.user if status in {"Validated", "No MineSite Required"} else None,
            validated_at=timezone.now() if status in {"Validated", "No MineSite Required"} else None,
            supersedes_version=previous,
        )

    def _audit(self, action, mapping, previous, current, reason):
        return MappingAuditLog.objects.create(
            actor=self.user, action=action, entity_type="AccountMineSiteMapping", entity_id=str(mapping.id),
            previous_value_json=previous, new_value_json=current, reason=reason,
            source_ip=self.source_ip, application_version=self.application_version,
        )
