from __future__ import annotations

from collections import OrderedDict
import re


CORE_METRICS = OrderedDict(
    (
        ("availability", {
            "label": "Physical Availability",
            "measure": "[Availability New]",
            "unit": "percentage",
            "precision": 2,
            "optimization": "maximize",
        }),
        ("mtbs", {
            "label": "MTBS",
            "measure": "[MTBS Per Equip]",
            "unit": "hours",
            "precision": 2,
            "optimization": "maximize",
        }),
        ("mtbf", {
            "label": "MTBF",
            "measure": "[MTBF Per Equip]",
            "unit": "hours",
            "precision": 2,
            "optimization": "maximize",
        }),
        ("mttr", {
            "label": "MTTR",
            "measure": "[MTTR Per Equip]",
            "unit": "hours",
            "precision": 2,
            "optimization": "minimize",
        }),
        ("planned_downtime_percentage", {
            "label": "Planned Downtime",
            "measure": "[% PlannedHours DT]",
            "unit": "percentage",
            "precision": 2,
            "optimization": "target_based",
        }),
        ("unplanned_downtime_percentage", {
            "label": "Unplanned Downtime",
            "measure": "[% UnplannedHours DT]",
            "unit": "percentage",
            "precision": 2,
            "optimization": "minimize",
        }),
    )
)

MONTH_NAMES = {
    "en": ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"),
    "fr": ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"),
}


def _period_label(value, language: str) -> str:
    period = str(value or "Year to Date")
    match = re.fullmatch(r"(20\d{2})-(0[1-9]|1[0-2])/(20\d{2})-(0[1-9]|1[0-2])", period)
    if not match:
        return period
    start_year, start_month, end_year, end_month = match.groups()
    start_label = MONTH_NAMES[language][int(start_month) - 1]
    end_label = MONTH_NAMES[language][int(end_month) - 1]
    connector = " à " if language == "fr" else " to "
    if start_year == end_year:
        return f"{start_label}{connector}{end_label} {end_year}"
    return f"{start_label} {start_year}{connector}{end_label} {end_year}"

METRIC_BUNDLES = {
    "fleet_performance_core": list(CORE_METRICS),
    "reliability_core": ["mtbs", "mtbf", "mttr"],
    "downtime_mix": ["planned_downtime_percentage", "unplanned_downtime_percentage"],
    "availability_reliability": ["availability", "mtbs", "mtbf", "mttr"],
}

PERFORMANCE_INTENTS = {
    "fleet_performance_overview",
    "reliability_overview",
    "multi_kpi_summary",
    "single_kpi",
    "site_performance",
    "model_performance",
    "equipment_performance",
    "serial_performance",
    "entity_comparison",
    "period_comparison",
    "trend_analysis",
    "ranking",
    "planned_unplanned_analysis",
    "most_impacted_equipment",
    "down_hours_by_compartment",
    "down_hours_by_equipment",
    "component_analysis",
    "pm_analysis",
    "smu_tracking",
    "benchmark_analysis",
}

_METRIC_MARKERS = OrderedDict(
    (
        ("planned_downtime_percentage", (
            "planned downtime", "planned hours", "planned dt",
            "downtime planifie", "downtime planifié", "arrets planifies", "arrêts planifiés",
        )),
        ("unplanned_downtime_percentage", (
            "unplanned downtime", "unplanned hours", "unplanned dt",
            "downtime non planifie", "downtime non planifié", "arrets non planifies", "arrêts non planifiés",
        )),
        ("availability", (
            "physical availability", "availability", "disponibilite physique",
            "disponibilité physique", "disponibilite", "disponibilité",
        )),
        ("mtbs", ("mtbs", "mean time between stoppages", "temps moyen entre arrets", "temps moyen entre arrêts")),
        ("mtbf", ("mtbf", "mean time between failures", "temps moyen entre pannes")),
        ("mttr", ("mttr", "mean time to repair", "temps moyen de reparation", "temps moyen de réparation")),
    )
)


def _text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").casefold()).strip()


def detect_requested_metrics(question: str) -> list[str]:
    text = _text(question)
    metrics = []
    for code, markers in _METRIC_MARKERS.items():
        if any(marker in text for marker in markers):
            metrics.append(code)
    return metrics


def resolve_metric_bundle(question: str, metrics: list[str] | None = None) -> str | None:
    text = _text(question)
    requested = list(metrics or [])
    if any(marker in text for marker in ("planned versus unplanned", "planned vs unplanned", "downtime mix", "planifie versus", "planifié versus")):
        return "downtime_mix"
    if any(marker in text for marker in ("reliability", "fiabilite", "fiabilité", "reliability kpi")):
        return "reliability_core"
    if "performance" in text and not requested:
        return "fleet_performance_core"
    if len(requested) > 1:
        if requested == METRIC_BUNDLES["reliability_core"]:
            return "reliability_core"
        if set(requested) == set(METRIC_BUNDLES["downtime_mix"]):
            return "downtime_mix"
    return None


def metrics_for_intent(intent: dict) -> list[str]:
    requested = intent.get("metrics")
    if isinstance(requested, list):
        metrics = [str(code) for code in requested if str(code) in CORE_METRICS]
        if metrics:
            return metrics
    bundle = str(intent.get("metric_bundle") or "")
    if bundle in METRIC_BUNDLES:
        return list(METRIC_BUNDLES[bundle])
    metric = str(intent.get("metric") or intent.get("primary_metric") or "")
    return [metric] if metric in CORE_METRICS else []


def enrich_fleet_performance_intent(intent: dict, question: str = "") -> dict:
    enriched = dict(intent or {})
    requested = detect_requested_metrics(question)
    if requested:
        enriched["metrics"] = requested
        enriched["metric"] = requested[0]
        enriched["primary_metric"] = requested[0]
    bundle = resolve_metric_bundle(question, requested)
    if bundle:
        enriched["metric_bundle"] = bundle
        enriched["metrics"] = list(METRIC_BUNDLES[bundle])
        if len(enriched["metrics"]) == 1:
            enriched["metric"] = enriched["metrics"][0]
    intent_type = str(enriched.get("intent_type") or "single_kpi")
    if intent_type == "benchmark_analysis" and not requested and not bundle:
        bundle = "fleet_performance_core"
        enriched["metric_bundle"] = bundle
        enriched["metrics"] = list(METRIC_BUNDLES[bundle])
    if intent_type in {"benchmark_analysis", "smu_tracking", "pm_analysis", "component_analysis"}:
        metric = str(enriched.get("metric") or "")
        if metric and metric not in CORE_METRICS:
            enriched["metric"] = None
            enriched["primary_metric"] = None
    if bundle == "fleet_performance_core" and intent_type in {"performance_overview", "single_kpi"}:
        enriched["intent_type"] = "fleet_performance_overview"
    elif bundle == "reliability_core" and intent_type in {"performance_overview", "single_kpi", "multi_kpi_summary"}:
        enriched["intent_type"] = "reliability_overview"
    elif bundle == "downtime_mix" and intent_type in {"single_kpi", "multi_kpi_summary"}:
        enriched["intent_type"] = "planned_unplanned_analysis"
    elif len(enriched.get("metrics") or []) > 1 and intent_type == "single_kpi":
        enriched["intent_type"] = "multi_kpi_summary"
    if enriched.get("intent_type") in PERFORMANCE_INTENTS:
        enriched["capability"] = "fleet_performance"
        filters = dict(enriched.get("filters") or {})
        if enriched["intent_type"] in {
            "single_kpi", "fleet_performance_overview", "reliability_overview", "multi_kpi_summary",
            "site_performance", "model_performance", "equipment_performance", "serial_performance",
        }:
            filters.setdefault("period", "year to date")
        enriched["filters"] = filters
    return enriched


def normalize_result_metrics(row: dict) -> list[dict]:
    normalized = []
    normalized_keys = {
        re.sub(r"[^a-z0-9]+", "", str(key).casefold()): value
        for key, value in (row or {}).items()
    }
    for code, config in CORE_METRICS.items():
        candidates = (
            config["label"], config["measure"].strip("[]"), code,
        )
        value = None
        for candidate in candidates:
            key = re.sub(r"[^a-z0-9]+", "", candidate.casefold())
            if key in normalized_keys:
                value = normalized_keys[key]
                break
        if value is None:
            continue
        try:
            raw_value = float(value)
        except (TypeError, ValueError):
            raw_value = None
        if raw_value is None:
            formatted = "Not available"
        elif config["unit"] == "percentage":
            formatted = f"{raw_value * 100:.{config['precision']}f}%"
        else:
            formatted = f"{raw_value:,.{config['precision']}f} h"
        normalized.append({
            "code": code,
            "label": config["label"],
            "raw_value": raw_value,
            "formatted_value": formatted,
            "unit": config["unit"],
            "optimization": config["optimization"],
            "status": None,
        })
    return normalized


def coverage_from_row(row: dict) -> dict:
    normalized = {
        re.sub(r"[^a-z0-9]+", "", str(key).casefold()): value
        for key, value in (row or {}).items()
    }
    try:
        fleet_equipment = int(normalized.get("fleetequipment"))
    except (TypeError, ValueError):
        fleet_equipment = None
    try:
        equipment_with_data = int(normalized.get("equipmentwithdata"))
    except (TypeError, ValueError):
        equipment_with_data = None
    without_data = (
        max(fleet_equipment - equipment_with_data, 0)
        if fleet_equipment is not None and equipment_with_data is not None else None
    )
    percentage = (
        equipment_with_data / fleet_equipment
        if fleet_equipment and equipment_with_data is not None else None
    )
    return {
        "fleet_equipment": fleet_equipment,
        "equipment_with_data": equipment_with_data,
        "equipment_without_data": without_data,
        "coverage_percentage": percentage,
    }


def deterministic_performance_answer(intent: dict, rows: list[dict], language: str = "en") -> str:
    if not rows:
        return (
            "Aucune donnée de performance n'est disponible pour le contexte sélectionné."
            if language == "fr" else
            "No performance data is available for the selected context."
        )
    filters = intent.get("filters") or {}
    scope_code = next(
        (
            code for code in (
                "minesite", "site", "model", "product_group", "family",
                "equipment", "serial_number",
            )
            if filters.get(code)
        ),
        "",
    )
    scope_value = filters.get(scope_code) if scope_code else None
    if isinstance(scope_value, list):
        conjunction = " et " if language == "fr" else " and "
        if len(scope_value) > 1:
            scope_values = ", ".join(str(value) for value in scope_value[:-1]) + conjunction + str(scope_value[-1])
        else:
            scope_values = str(scope_value[0]) if scope_value else ""
        labels = {
            "model": ("Modèles", "Models"),
            "product_group": ("Familles", "Product Groups"),
            "family": ("Familles", "Equipment Families"),
            "minesite": ("MineSites", "MineSites"),
            "site": ("Sites", "Sites"),
            "equipment": ("Équipements", "Equipment"),
            "serial_number": ("Numéros de série", "Serial Numbers"),
        }
        label = labels.get(scope_code, ("Périmètre", "Scope"))[0 if language == "fr" else 1]
        scope = f"{label} {scope_values}"
    else:
        scope = scope_value or ("Flotte autorisée" if language == "fr" else "Authorized fleet")
    period = _period_label(filters.get("period") or "Year to Date", language)
    intent_type = str(intent.get("intent_type") or "single_kpi")
    if len(rows) > 1 and intent_type in {"entity_comparison", "period_comparison", "benchmark_analysis"}:
        return (
            f"La comparaison de {len(rows)} entités ({period}) est disponible ci-dessous."
            if language == "fr" else
            f"The comparison of {len(rows)} entities ({period}) is available below."
        )
    if len(rows) > 1 and intent_type == "trend_analysis":
        return (
            f"La tendance de {scope} contient {len(rows)} périodes ({period})."
            if language == "fr" else
            f"The {scope} trend contains {len(rows)} periods ({period})."
        )
    if len(rows) > 1 and intent_type == "ranking":
        return (
            f"Le classement de {scope} contient {len(rows)} résultats."
            if language == "fr" else
            f"The {scope} ranking contains {len(rows)} results."
        )
    metrics = normalize_result_metrics(rows[0])
    values = ", ".join(f"{item['label']}: {item['formatted_value']}" for item in metrics)
    if language == "fr":
        return f"Performance de {scope} ({period}) : {values}." if values else f"La performance de {scope} est disponible ci-dessous."
    return f"{scope} performance ({period}): {values}." if values else f"{scope} performance is available below."
