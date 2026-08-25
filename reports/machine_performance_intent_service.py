from __future__ import annotations

import re


INTENT_TYPES = {
    "single_kpi",
    "performance_overview",
    "equipment_detail",
    "downtime_drivers",
    "trend_analysis",
    "entity_comparison",
    "period_comparison",
    "ranking",
    "affected_equipment",
    "downtime_events",
    "root_cause_analysis",
    "repeated_failures",
    "comment_analysis",
    "smcs_breakdown",
    "powerbi_navigation",
    "follow_up",
    "clarification_required",
}

QUERY_INTENT_ALIASES = {
    "trend_analysis": "trend",
    "entity_comparison": "comparison",
    "period_comparison": "comparison",
    "powerbi_navigation": "navigation",
    "follow_up": "single_kpi",
}


def _text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").casefold()).strip()


def detect_machine_performance_intent(question: str, fallback: str = "single_kpi") -> str:
    text = _text(question)
    explicit_metric = any(marker in text for marker in (
        "availability", "disponibilité", "disponibilite", "mtbf", "mttr", "mtbs",
        "downtime hours", "heures de downtime", "heures d'arrêt", "heures d’arret",
    ))
    if any(marker in text for marker in ("downtime driver", "downtime breakdown", "causes of downtime", "causing the downtime", "drivers de downtime")):
        return "downtime_drivers"
    if any(marker in text for marker in (
        "open the report", "open report", "open power bi", "show the report",
        "open prime movers", "ouvre le rapport", "ouvrir le rapport", "affiche le rapport",
    )):
        return "powerbi_navigation"
    if any(marker in text for marker in ("compare", "comparison", "comparaison")):
        month_matches = re.findall(
            r"\b(?:jan(?:uary|vier)?|feb(?:ruary)?|f[eé]vrier|mar(?:ch|s)?|apr(?:il)?|avril|may|mai|jun(?:e)?|juin|jul(?:y)?|juillet|aug(?:ust)?|ao[uû]t|sep(?:tember)?|septembre|oct(?:ober)?|octobre|nov(?:ember)?|novembre|dec(?:ember)?|d[eé]cembre)\b",
            text,
        )
        year_matches = re.findall(r"\b20\d{2}\b", text)
        if len(month_matches) >= 2 or len(year_matches) >= 2:
            return "period_comparison"
    rules = (
        ("root_cause_analysis", ("root cause", "why ", "pourquoi", "what caused", "cause de", "explain the decrease")),
        ("period_comparison", ("previous month", "previous period", "last year", "versus last", "vs last", "mois précédent")),
        ("entity_comparison", ("compare", "comparison", "versus", " vs ", "comparaison", "comparez")),
        ("trend_analysis", ("trend", "tendance", "evolution", "évolution", "monthly", "mensuel", "over time", "par mois")),
        ("ranking", ("highest", "lowest", "top ", "bottom ", "ranking", "rank ", "best", "worst", "classement", "meilleur", "plus faible")),
        ("smcs_breakdown", ("smcs", "subcomponent", "sous-composant", "component breakdown", "system breakdown")),
        ("repeated_failures", ("repeated failure", "repeat failure", "recurring", "repetitive", "récurrent", "pannes répét")),
        ("comment_analysis", ("analyze comments", "analyse comments", "maintenance comments", "summarize comments", "comment themes", "commentaires")),
        ("affected_equipment", ("affected equipment", "affected machine", "impacted equipment", "machines concern", "équipements impact")),
        ("downtime_events", ("downtime event", "events for", "event list", "incidents", "événements de downtime")),
        ("equipment_detail", ("serial number", "equipment serial", "show me machine", "show equipment", "machine ", "equipment ")),
        ("performance_overview", ("performance overview", "fleet performance", "how is the fleet", "vue d'ensemble", "aperçu de performance")),
    )
    for intent_type, markers in rules:
        if any(marker in text for marker in markers):
            # A serial number narrows a KPI query to one machine; it does not
            # turn an explicit metric request into a generic equipment profile.
            if intent_type == "equipment_detail" and explicit_metric:
                return "single_kpi"
            return intent_type
    normalized_fallback = str(fallback or "single_kpi").strip().lower()
    return {
        "trend": "trend_analysis",
        "comparison": "entity_comparison",
        "navigation": "powerbi_navigation",
        "follow_up_navigation": "powerbi_navigation",
    }.get(normalized_fallback, normalized_fallback if normalized_fallback in INTENT_TYPES else "single_kpi")


def infer_scope(intent: dict) -> str:
    filters = intent.get("filters") if isinstance(intent.get("filters"), dict) else {}
    comparison = intent.get("comparison") if isinstance(intent.get("comparison"), dict) else {}
    multiple = {
        "minesite": "multiple_minesites",
        "customer": "multiple_customers",
        "model": "multiple_models",
        "serial_number": "multiple_equipment",
    }
    for code, scope in multiple.items():
        values = comparison.get(code)
        if isinstance(values, list) and len(values) > 1:
            return scope
    if filters.get("serial_number"):
        return "serial_number"
    if filters.get("downtime_driver"):
        return "downtime_driver"
    if filters.get("component"):
        return "component"
    if filters.get("model"):
        return "model"
    if filters.get("family"):
        return "equipment_family"
    if filters.get("minesite") or filters.get("site"):
        return "minesite"
    if filters.get("customer"):
        return "customer"
    return "global"


def enrich_machine_performance_intent(intent: dict, question: str = "") -> dict:
    enriched = dict(intent or {})
    enriched["domain"] = "machine_performance"
    enriched["intent_type"] = detect_machine_performance_intent(
        question,
        enriched.get("intent_type") or "single_kpi",
    )
    if enriched["intent_type"] in {
        "downtime_drivers", "affected_equipment", "downtime_events",
        "repeated_failures", "comment_analysis", "smcs_breakdown",
    } and enriched.get("metric") in {"downtime", "downtime_hours"}:
        enriched["metric"] = None
    enriched["scope_type"] = infer_scope(enriched)
    enriched["primary_metric"] = enriched.get("primary_metric") or enriched.get("metric")
    enriched.setdefault("secondary_metrics", [])
    enriched.setdefault("group_by", [])
    enriched.setdefault("ranking", enriched.get("comparison") if enriched["intent_type"] == "ranking" else None)
    enriched.setdefault("comparison", None)
    enriched["diagnostic_request"] = enriched["intent_type"] in {
        "downtime_drivers", "root_cause_analysis", "repeated_failures",
        "comment_analysis", "smcs_breakdown",
    }
    enriched["root_cause_request"] = enriched["intent_type"] == "root_cause_analysis"
    enriched["navigation_request"] = enriched.get("navigation") or None
    enriched.setdefault("requires_clarification", False)
    enriched.setdefault("clarification_question", None)
    enriched["query_intent_type"] = QUERY_INTENT_ALIASES.get(
        enriched["intent_type"], enriched["intent_type"]
    )
    return enriched
