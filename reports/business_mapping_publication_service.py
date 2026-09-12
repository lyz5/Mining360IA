from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.db.models import Max, Sum
from django.utils import timezone

from .business_mapping_access_service import has_mapping_permission
from .business_mapping_conflict_service import BusinessMappingConflictService
from .models import AccountMineSiteMapping, MappingAuditLog, MappingPublication, RevenueSiteAllocationRule


class MappingPublicationError(RuntimeError):
    def __init__(self, message, *, code="PUBLICATION_ERROR", status=400):
        super().__init__(message)
        self.code = code
        self.status = status


def _published_snapshot(queryset=None):
    mappings = (queryset or AccountMineSiteMapping.objects.filter(active=True, relationship_status__in=["Validated", "Published"])).select_related(
        "business_account", "minesite"
    ).prefetch_related("business_account__source_records", "business_account__key_account_memberships__key_account")
    rows = []
    for item in mappings:
        source_records = list(item.business_account.source_records.filter(active=True).values(
            "source_system", "source_record_id", "code_cic", "company_code", "branch_code", "country", "operating_countries_json",
        ))
        membership = next((entry for entry in item.business_account.key_account_memberships.all() if entry.active and entry.key_account.active), None)
        operating_countries = {
            str(country).strip()
            for record in source_records for country in (record.get("operating_countries_json") or [])
            if str(country).strip()
        }
        business_country = item.business_account.assigned_operating_country or (
            next(iter(operating_countries)) if len(operating_countries) == 1 else ""
        )
        rows.append({
            "mapping_id": str(item.id), "mapping_version": item.current_version,
            "account_id": str(item.business_account_id), "account_code": item.business_account.canonical_account_code,
            "account_name": item.business_account.canonical_account_name,
            "business_country": business_country,
            "key_account_id": str(membership.key_account_id) if membership else None,
            "key_account_name": membership.key_account.key_account_name if membership else None,
            "minesite_id": str(item.minesite_id) if item.minesite_id else None,
            "minesite_name": item.minesite.canonical_minesite_name if item.minesite_id else None,
            "role": item.account_role, "valid_from": item.valid_from.isoformat() if item.valid_from else None,
            "valid_to": item.valid_to.isoformat() if item.valid_to else None,
            "allocation_status": item.revenue_allocation_status,
            "source_records": source_records,
            "source_account_codes": sorted({record["source_record_id"] for record in source_records}),
        })
    return rows


class MappingPublicationService:
    def __init__(self, user, source_ip=None):
        self.user = user
        self.source_ip = source_ip

    def preview(self):
        rows = _published_snapshot()
        current = MappingPublication.objects.filter(status="Published").order_by("-version").first()
        old = {item["mapping_id"]: item for item in (current.snapshot_json.get("mappings", []) if current else [])}
        new = {item["mapping_id"]: item for item in rows}
        conflicts = BusinessMappingConflictService.list_conflicts()
        return {
            "mapping_count": len(rows), "account_count": len({row["account_id"] for row in rows}),
            "minesite_count": len({row["minesite_id"] for row in rows if row["minesite_id"]}),
            "changes": {
                "added": [new[key] for key in new.keys() - old.keys()],
                "removed": [old[key] for key in old.keys() - new.keys()],
                "changed": [new[key] for key in new.keys() & old.keys() if new[key] != old[key]],
            },
            "conflicts": conflicts,
            "can_publish": not any(item.get("severity") == "Critical" for item in conflicts),
        }

    @transaction.atomic
    def publish(self, reason=""):
        if not has_mapping_permission(self.user, "publish_business_mapping"):
            raise MappingPublicationError("You do not have permission to publish mappings.", code="PERMISSION_DENIED", status=403)
        preview = self.preview()
        if not preview["can_publish"]:
            raise MappingPublicationError("Resolve critical mapping conflicts before publication.", code="UNRESOLVED_CONFLICTS", status=409)
        list(AccountMineSiteMapping.objects.select_for_update().filter(active=True, relationship_status__in=["Validated", "Published"]).values_list("pk", flat=True))
        version = (MappingPublication.objects.aggregate(value=Max("version"))["value"] or 0) + 1
        rows = _published_snapshot()
        total_allocated = RevenueSiteAllocationRule.objects.filter(status="Validated").aggregate(value=Sum("allocation_percentage"))["value"] or Decimal("0")
        publication = MappingPublication.objects.create(
            version=version, status="Published", mapping_count=len(rows),
            account_count=len({row["account_id"] for row in rows}),
            minesite_count=len({row["minesite_id"] for row in rows if row["minesite_id"]}),
            revenue_coverage=min(Decimal("100"), total_allocated), fleet_coverage=0,
            snapshot_json={"mappings": rows}, change_summary_json=preview["changes"],
            created_by=self.user, published_by=self.user, published_at=timezone.now(),
        )
        ids = [row["mapping_id"] for row in rows]
        AccountMineSiteMapping.objects.filter(pk__in=ids, relationship_status="Validated").update(relationship_status="Published")
        MappingAuditLog.objects.create(actor=self.user, action="Mapping published", entity_type="MappingPublication", entity_id=str(publication.id), new_value_json={"version": version, "mapping_count": len(rows)}, reason=reason, source_ip=self.source_ip)
        return publication

    @transaction.atomic
    def rollback(self, publication, reason):
        if not has_mapping_permission(self.user, "rollback_business_mapping"):
            raise MappingPublicationError("You do not have permission to roll back mappings.", code="PERMISSION_DENIED", status=403)
        if not reason.strip():
            raise MappingPublicationError("A rollback reason is required.")
        version = (MappingPublication.objects.select_for_update().aggregate(value=Max("version"))["value"] or 0) + 1
        snapshot = publication.snapshot_json or {"mappings": []}
        rolled_back = MappingPublication.objects.create(
            version=version, status="Published", mapping_count=len(snapshot.get("mappings", [])),
            account_count=len({row["account_id"] for row in snapshot.get("mappings", [])}),
            minesite_count=len({row["minesite_id"] for row in snapshot.get("mappings", []) if row.get("minesite_id")}),
            revenue_coverage=publication.revenue_coverage, fleet_coverage=publication.fleet_coverage,
            snapshot_json=snapshot, change_summary_json={"rollback_of": publication.version},
            created_by=self.user, published_by=self.user, published_at=timezone.now(), rollback_of=publication,
        )
        MappingAuditLog.objects.create(actor=self.user, action="Mapping publication rollback", entity_type="MappingPublication", entity_id=str(rolled_back.id), previous_value_json={"current_version": version - 1}, new_value_json={"version": version, "rollback_of": publication.version}, reason=reason, source_ip=self.source_ip)
        return rolled_back
