from __future__ import annotations

from dataclasses import asdict, dataclass
import re

from django.db.models import Count, Q

from reports.models import EquipmentFleetAnalysis
from reports.business_mapping_access_service import authorized_minesite_names

from .minesite_resolution import resolve_minesite_from_question


@dataclass(frozen=True)
class FleetInventoryResult:
    site: str
    equipment_count: int
    serial_count: int
    models: tuple[dict, ...]
    source_table: str

    def as_dict(self) -> dict:
        return asdict(self)


def _normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _scoped_records(user):
    records = EquipmentFleetAnalysis.objects.filter(active=True)
    authorized = authorized_minesite_names(user)
    if authorized is not None:
        if not authorized:
            return records.none()
        records = records.filter(site__in=authorized)
    return records


def resolve_site_from_question(question: str, *, user) -> str | None:
    resolution = resolve_minesite_from_question(question, user=user)
    return resolution.semantic_name if resolution and not resolution.ambiguous else None


def fleet_inventory_for_site(site: str, *, user) -> FleetInventoryResult:
    authorized = authorized_minesite_names(user)
    if authorized is not None and site.casefold() not in {value.casefold() for value in authorized}:
        raise PermissionError("MineSite is outside the authorized scope.")
    records = EquipmentFleetAnalysis.objects.filter(active=True, site__iexact=site)
    model_rows = tuple(
        records.exclude(model="")
        .values("model")
        .annotate(equipment_count=Count("serial_number", distinct=True))
        .order_by("-equipment_count", "model")[:10]
    )
    serial_count = records.exclude(serial_number="").values("serial_number").distinct().count()
    equipment_count = records.exclude(equipment_id="").values("equipment_id").distinct().count()
    if not equipment_count:
        equipment_count = serial_count
    return FleetInventoryResult(
        site=site,
        equipment_count=equipment_count,
        serial_count=serial_count,
        models=model_rows,
        source_table="EquipmentList_MiningProd / bm_equipment_fleet_analysis",
    )


def _machine_row(record) -> dict:
    return {
        "site": record.site,
        "equipment": record.equipment,
        "model": record.model,
        "serial_number": record.serial_number,
        "equipment_family": record.equipment_family or None,
        "brand": record.brand or None,
        "status": record.source_status or None,
        "smu": float(record.smu) if record.smu is not None else None,
        "source_last_seen_at": record.source_last_seen_at.isoformat(),
    }


def _serial_from_question(question: str) -> str | None:
    match = re.search(
        r"(?:serial(?:\s+number)?|num[eé]ro\s+de\s+s[eé]rie|\bsn\b)\s*[:#-]?\s*([a-z0-9-]{5,})",
        question,
        flags=re.IGNORECASE,
    )
    return match.group(1).strip() if match else None


def fleet_analysis_from_question(question: str, *, user) -> dict | None:
    normalized = _normalized(question)
    records = _scoped_records(user)
    source_table = "EquipmentList_MiningProd / bm_equipment_fleet_analysis"
    serial = _serial_from_question(question)
    if serial:
        machine = records.filter(serial_number__iexact=serial).order_by("-source_last_seen_at").first()
        return {
            "kind": "machine_detail" if machine else "machine_not_found",
            "serial_number": serial,
            "machine": _machine_row(machine) if machine else None,
            "source_table": source_table,
        }

    coverage_requested = any(
        term in normalized for term in ("couverture", "coverage", "qualite", "quality", "manquant", "missing")
    )
    site = resolve_site_from_question(question, user=user)
    if not site and not coverage_requested:
        return None
    if site:
        records = records.filter(site__iexact=site)

    total = records.count()
    coverage = {
        "serial_number": round(100 * records.exclude(serial_number="").count() / total, 1) if total else None,
        "model": round(100 * records.exclude(model="").count() / total, 1) if total else None,
        "equipment_family": round(100 * records.exclude(equipment_family="").count() / total, 1) if total else None,
        "brand": round(100 * records.exclude(brand="").count() / total, 1) if total else None,
    }
    missing = records.aggregate(
        serial_number=Count("id", filter=Q(serial_number="")),
        model=Count("id", filter=Q(model="")),
        equipment_family=Count("id", filter=Q(equipment_family="")),
        brand=Count("id", filter=Q(brand="")),
    )
    by_model = list(
        records.exclude(model="").values("model").annotate(equipment_count=Count("serial_number", distinct=True)).order_by("-equipment_count", "model")[:25]
    )
    by_family = list(
        records.exclude(equipment_family="").values("equipment_family").annotate(equipment_count=Count("serial_number", distinct=True)).order_by("-equipment_count", "equipment_family")[:25]
    )
    rows = [_machine_row(row) for row in records.order_by("model", "serial_number")[:10000]]
    return {
        "kind": "fleet_coverage" if coverage_requested else "site_inventory",
        "site": site,
        "equipment_count": records.exclude(equipment_id="").values("equipment_id").distinct().count() or records.exclude(serial_number="").values("serial_number").distinct().count(),
        "serial_count": records.exclude(serial_number="").values("serial_number").distinct().count(),
        "model_count": records.exclude(model="").values("model").distinct().count(),
        "family_count": records.exclude(equipment_family="").values("equipment_family").distinct().count(),
        "models": by_model,
        "families": by_family,
        "coverage_percent": coverage,
        "missing_count": missing,
        "rows": rows,
        "rows_returned": len(rows),
        "rows_total": total,
        "is_complete": len(rows) == total,
        "source_table": source_table,
    }
