from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Max, Sum

from .business_mapping_normalization_service import normalize_business_name
from .business_mapping_source_service import MINING_DIVISION, MINING_REVENUE_LOBS, UNCLASSIFIED_REVENUE_LOB
from .business_review_confidence_service import BusinessReviewDataConfidenceService
from .models import (
    BusinessAccount,
    BusinessReviewSnapshot,
    EquipmentFleetAnalysis,
    MappingPublication,
    MappingSynchronizationRun,
    MineSite,
    RevenueSourceSnapshot,
)


def _number(value) -> float:
    return float(value or 0)


class BusinessReviewSnapshotService:
    RULE_VERSION = "1.0"

    @classmethod
    def latest_publication(cls):
        return MappingPublication.objects.filter(status="Published").order_by("-version").first()

    @classmethod
    def latest_source_run(cls):
        revenue = RevenueSourceSnapshot.objects.filter(active=True).select_related("synchronization_run").first()
        return revenue.synchronization_run if revenue else MappingSynchronizationRun.objects.filter(status__in=["Completed", "Partial"]).first()

    @classmethod
    @transaction.atomic
    def generate(cls, user=None, publication=None):
        publication = publication or cls.latest_publication()
        if not publication:
            return None
        source_run = cls.latest_source_run()
        if not source_run:
            return None
        existing = BusinessReviewSnapshot.objects.filter(
            mapping_publication=publication,
            source_synchronization=source_run,
            business_rule_version=cls.RULE_VERSION,
        ).first()
        if existing:
            return existing

        rows = list((publication.snapshot_json or {}).get("mappings", []))
        source_codes = sorted({code for row in rows for code in row.get("source_account_codes", []) if code})
        site_names = sorted({normalize_business_name(row.get("minesite_name")) for row in rows if row.get("minesite_name")})
        mapped_account_ids = {row.get("account_id") for row in rows if row.get("account_id")}

        revenue = RevenueSourceSnapshot.objects.filter(active=True, division__iexact=MINING_DIVISION)
        revenue_total = revenue.aggregate(value=Sum("revenue_ytd_eur"))["value"] or Decimal("0")
        assigned = revenue.filter(source_account_code__in=source_codes)
        assigned_total = assigned.aggregate(value=Sum("revenue_ytd_eur"))["value"] or Decimal("0")
        assigned_previous = assigned.aggregate(value=Sum("revenue_previous_year_eur"))["value"] or Decimal("0")
        by_lob = {
            row["lob"]: _number(row["value"])
            for row in assigned.values("lob").annotate(value=Sum("revenue_ytd_eur"))
        }

        fleet = EquipmentFleetAnalysis.objects.filter(active=True)
        fleet_total = fleet.count()
        fleet_linked = fleet.filter(normalized_site__in=site_names).count()
        total_accounts = BusinessAccount.objects.filter(active=True).count()
        total_sites = MineSite.objects.filter(active=True).count()
        metrics = {
            "mining_revenue_ytd_eur": _number(assigned_total),
            "mining_revenue_previous_year_eur": _number(assigned_previous),
            "revenue_by_lob": {lob: by_lob.get(lob, 0) for lob in (*MINING_REVENUE_LOBS, UNCLASSIFIED_REVENUE_LOB)},
            "unclassified_revenue_eur": by_lob.get(UNCLASSIFIED_REVENUE_LOB, 0),
            "fleet_count": fleet_linked,
            "fleet_total": fleet_total,
            "revenue_per_equipment_eur": _number(assigned_total / fleet_linked) if fleet_linked else None,
            "revenue_assigned_eur": _number(assigned_total),
            "unallocated_revenue_eur": _number(revenue_total - assigned_total),
            "revenue_coverage_pct": round(_number(assigned_total / revenue_total * 100), 1) if revenue_total else 0,
            "fleet_coverage_pct": round(fleet_linked / fleet_total * 100, 1) if fleet_total else 0,
            "account_coverage_pct": round(len(mapped_account_ids) / total_accounts * 100, 1) if total_accounts else 0,
            "published_account_count": len(mapped_account_ids),
            "published_minesite_count": len(site_names),
            "total_account_count": total_accounts,
            "total_minesite_count": total_sites,
        }
        confidence = BusinessReviewDataConfidenceService.evaluate(publication=publication, source_run=source_run, metrics=metrics)
        context = {
            "mapping_publication_id": str(publication.id),
            "published_mapping_version": publication.version,
            "source_synchronization_id": str(source_run.id),
            "revenue_snapshot_at": source_run.completed_at.isoformat() if source_run.completed_at else None,
            "fleet_snapshot_at": source_run.completed_at.isoformat() if source_run.completed_at else None,
            "period": (source_run.source_context_json or {}).get("revenue_period_kind", "YTD"),
            "period_year": (source_run.source_context_json or {}).get("revenue_period_year"),
            "data_through_date": (source_run.source_context_json or {}).get("semantic_data_through"),
            "currency": "EUR",
        }
        checksum = hashlib.sha256(json.dumps({"context": context, "metrics": metrics}, sort_keys=True).encode("utf-8")).hexdigest()
        snapshot = BusinessReviewSnapshot.objects.create(
            mapping_publication=publication,
            source_synchronization=source_run,
            business_rule_version=cls.RULE_VERSION,
            business_line_mapping_version="1.0",
            exchange_rate_version="SOURCE_CA_EURO",
            data_through_date=revenue.aggregate(value=Max("business_date"))["value"],
            currency="EUR",
            reconciliation_status="Reconciled",
            status="Limited" if confidence["warnings"] else "Ready",
            confidence_status=confidence["status"],
            context_json=context,
            metrics_json=metrics,
            warnings_json=confidence["warnings"],
            checksum=checksum,
            generated_by=user,
        )
        return snapshot

    @classmethod
    def site_portfolio(cls, snapshot, lens="ALL"):
        rows = list((snapshot.mapping_publication.snapshot_json or {}).get("mappings", []))
        by_site = defaultdict(lambda: {"account_ids": set(), "source_codes": set(), "roles": set()})
        for row in rows:
            if not row.get("minesite_name"):
                continue
            key = normalize_business_name(row["minesite_name"])
            by_site[key]["name"] = row["minesite_name"]
            by_site[key]["minesite_id"] = row.get("minesite_id")
            by_site[key]["account_ids"].add(row.get("account_id"))
            by_site[key]["source_codes"].update(row.get("source_account_codes", []))
            by_site[key]["roles"].add(row.get("role"))

        fleet_values = {
            row["normalized_site"]: row["value"]
            for row in EquipmentFleetAnalysis.objects.filter(active=True).values("normalized_site").annotate(value=Count("pk"))
        }
        all_source_codes = {code for item in by_site.values() for code in item["source_codes"]}
        revenue_query = RevenueSourceSnapshot.objects.filter(
            active=True,
            division__iexact=MINING_DIVISION,
            source_account_code__in=all_source_codes,
            lob__in=MINING_REVENUE_LOBS,
        )
        if lens in MINING_REVENUE_LOBS:
            revenue_query = revenue_query.filter(lob=lens)
        revenue_by_source = {
            row["source_account_code"]: row["value"] or Decimal("0")
            for row in revenue_query.values("source_account_code").annotate(value=Sum("revenue_ytd_eur"))
        }
        result = []
        for key, item in by_site.items():
            value = sum((revenue_by_source.get(code, Decimal("0")) for code in item["source_codes"]), Decimal("0"))
            fleet_count = fleet_values.get(key, 0)
            result.append({
                "entity_type": "MineSite",
                "entity_id": item["minesite_id"],
                "name": item["name"],
                "account_count": len(item["account_ids"]),
                "roles": sorted(role for role in item["roles"] if role),
                "revenue": _number(value),
                "fleet": fleet_count,
                "revenue_per_equipment": _number(value / fleet_count) if fleet_count else None,
                "classification": None,
            })
        return sorted(result, key=lambda item: (-item["revenue"], item["name"]))
