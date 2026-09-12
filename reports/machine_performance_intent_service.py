from __future__ import annotations

import re

from .fleet_performance_intelligence_service import enrich_fleet_performance_intent


INTENT_TYPES = {
    "single_kpi",
    "performance_overview",
    "fleet_performance_overview",
    "reliability_overview",
    "multi_kpi_summary",
    "site_performance",
    "model_performance",
    "equipment_performance",
    "serial_performance",
    "planned_unplanned_analysis",
    "most_impacted_equipment",
    "down_hours_by_compartment",
    "down_hours_by_equipment",
    "component_analysis",
    "pm_analysis",
    "smu_tracking",
    "benchmark_analysis",
    "equipment_detail",
    "fleet_inventory",
    "get_site_fleet",
    "get_site_fleet_by_model",
    "get_site_model_fleet",
    "get_fleet_count",
    "lookup_equipment_by_serial",
    "lookup_equipment_by_code",
    "export_current_fleet",
    "export_current_result",
    "fleet_follow_up",
    "fleet_clarification_required",
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
    plain_text = text.strip(" .?!")
    if plain_text in {"download it", "export it", "download them", "export them", "telecharge la flotte", "télécharge la flotte", "exporte le tableau en excel", "je veux le fichier excel"} or any(
        marker in text for marker in ("download the fleet", "download fleet", "export the fleet", "fleet in excel", "flotte en excel")
    ):
        return "export_current_fleet"
    explicit_metric = any(marker in text for marker in (
        "availability", "disponibilité", "disponibilite", "mtbf", "mttr", "mtbs",
        "downtime hours", "heures de downtime", "heures d'arrêt", "heures d’arret",
        "planned downtime", "unplanned downtime", "downtime planifié", "downtime non planifié",
    ))
    performance_request = explicit_metric or any(
        marker in text for marker in ("performance", "reliability", "fiabilite", "fiabilité", "fleet kpi", "kpi de la flotte")
    )
    if any(marker in text for marker in ("downtime driver", "downtime breakdown", "causes of downtime", "causing the downtime", "drivers de downtime")):
        return "downtime_drivers"
    if any(marker in text for marker in (
        "open the report", "open report", "open power bi", "show the report",
        "open prime movers", "ouvre le rapport", "ouvrir le rapport", "affiche le rapport",
    )):
        return "powerbi_navigation"
    serial_match = re.search(r"\b(?:serial(?: number| no)?|s/?n|num[eé]ro de s[eé]rie)\s*[:#-]?\s*([a-z0-9][a-z0-9 .-]{3,})\b", text)
    location_lookup = re.search(r"\b(?:where is|where is serial|ou se trouve|où se trouve|what model is|quel est le modele de)\s+([a-z0-9][a-z0-9.-]{4,})\b", text)
    standalone_identifier = re.fullmatch(r"(?=[a-z0-9 .-]*\d)[a-z0-9][a-z0-9 .-]{4,}", plain_text)
    if performance_request and serial_match:
        return "single_kpi" if explicit_metric else "serial_performance"
    if not performance_request and (serial_match or location_lookup or (
        standalone_identifier and len(text.split()) <= 2 and len(re.sub(r"\W", "", text)) >= 7
    )):
        return "lookup_equipment_by_serial"
    equipment_lookup = re.search(r"\b(?:show me|show|montre|affiche|equipment|machine)\s+([a-z]{1,4}-?\d{3,5})\b", text)
    if equipment_lookup and not explicit_metric:
        return "lookup_equipment_by_code"
    fleet_request = any(marker in text for marker in (
        "fleet at", "fleet of", "fleet for", "site fleet", "minesite fleet",
        "flotte de", "flotte du", "flotte à", "flotte a", "parc de machines",
        "machines sur site", "machines du site", "équipements du site", "equipements du site",
        "equipment at", "equipment fleet", "equipment inventory", "machine inventory",
        "liste les équipements", "liste les equipements", "liste des machines", "liste des équipements",
    )) or ("fleet" in text and any(text.startswith(marker) for marker in ("give me", "show me", "what is", "list")))
    if fleet_request:
        if performance_request:
            return "single_kpi" if explicit_metric else "performance_overview"
        if any(marker in text for marker in ("how many", "combien")):
            return "get_fleet_count"
        if any(marker in text for marker in ("by model", "par modèle", "par modele", "composition")):
            return "get_site_fleet_by_model"
        if re.search(r"\b(?:model(?:e)?\s*)?(?:\d{3}(?:\.\d+)?(?:\s+[a-z]{1,3})?|[a-z]{1,4}\d[\w.-]*)\b", text):
            return "get_site_model_fleet"
        return "get_site_fleet"
    if (
        any(marker in text for marker in ("planned", "planifie", "planifié"))
        and any(marker in text for marker in ("unplanned", "non planifie", "non planifié"))
    ):
        return "planned_unplanned_analysis"
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
        ("benchmark_analysis", ("benchmark", "peer average", "network average", "moyenne du reseau", "moyenne du réseau")),
        ("period_comparison", ("previous month", "previous period", "last year", "versus last", "vs last", "mois précédent")),
        ("entity_comparison", ("compare", "comparison", "versus", " vs ", "comparaison", "comparez")),
        ("trend_analysis", ("trend", "tendance", "evolution", "évolution", "monthly", "mensuel", "over time", "par mois")),
        ("ranking", ("highest", "lowest", "top ", "bottom ", "ranking", "rank ", "best", "worst", "classement", "meilleur", "plus faible")),
        ("planned_unplanned_analysis", ("planned versus unplanned", "planned vs unplanned", "downtime mix", "planifié versus", "planifie versus")),
        ("pm_analysis", ("after pm", "apres pm", "après pm", "pm analysis", "analyse pm", "pm-related")),
        ("smu_tracking", ("smu tracking", "suivi smu", "hours meter", "hour meter")),
        ("component_analysis", ("component analysis", "analyse composant", "composants impact", "components affect")),
        ("reliability_overview", ("reliability", "fiabilité", "fiabilite", "reliability kpi")),
        ("smcs_breakdown", ("smcs", "subcomponent", "sous-composant", "component breakdown", "system breakdown")),
        ("repeated_failures", ("repeated failure", "repeat failure", "recurring", "repetitive", "récurrent", "pannes répét")),
        ("comment_analysis", ("analyze comments", "analyse comments", "maintenance comments", "summarize comments", "comment themes", "commentaires")),
        ("affected_equipment", ("affected equipment", "affected machine", "impacted equipment", "machines concern", "équipements impact")),
        ("downtime_events", ("downtime event", "events for", "event list", "incidents", "événements de downtime")),
        ("equipment_detail", ("serial number", "equipment serial", "show me machine", "show equipment", "machine ", "equipment ")),
        ("performance_overview", ("performance overview", "fleet performance", "performance de la flotte", "how is the fleet", "vue d'ensemble", "aperçu de performance")),
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
        "family": "equipment_family",
        "product_group": "equipment_family",
    }
    for code, scope in multiple.items():
        values = comparison.get(code) or filters.get(code)
        if isinstance(values, list) and len(values) > 1:
            return scope
    if filters.get("serial_number"):
        return "serial_number"
    if filters.get("equipment"):
        return "equipment"
    if filters.get("downtime_driver"):
        return "downtime_driver"
    if filters.get("component"):
        return "component"
    if filters.get("model"):
        return "model"
    if filters.get("family") or filters.get("product_group"):
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
    text = _text(question)
    filters = dict(enriched.get("filters") or {})
    if enriched["intent_type"] in {
        "get_site_fleet", "get_site_fleet_by_model", "get_site_model_fleet", "get_fleet_count",
    } and not (filters.get("minesite") or filters.get("site")):
        site_match = re.search(
            r"(?:give me|show me|what is|list)?\s*(?:the\s+)?(.+?)\s+(?:equipment\s+)?fleet\b",
            text,
        ) or re.search(r"\bfleet\s+(?:at|of|for)\s+(.+?)(?:\?|$)", text)
        if site_match:
            site = site_match.group(1).strip(" .?!")
            if filters.get("model"):
                site = re.sub(rf"\s+{re.escape(str(filters['model']).casefold())}$", "", site).strip()
            site = re.sub(r"^(?:give me|show me|what is|list)\s+", "", site).strip()
            if site and site not in {"site", "minesite", "equipment", "machine"}:
                filters["minesite"] = site.title()
    if enriched["intent_type"] == "lookup_equipment_by_serial":
        match = re.search(r"\b(?:serial(?: number| no)?|s/?n|num[eé]ro de s[eé]rie)\s*[:#-]?\s*([a-z0-9][a-z0-9 .-]{3,})\b", text)
        location = re.search(r"\b(?:where is|where is serial|ou se trouve|où se trouve|what model is|quel est le modele de)\s+([a-z0-9][a-z0-9.-]{4,})\b", text)
        candidate = (match.group(1) if match else (location.group(1) if location else text)).strip(" .?!")
        token = re.search(r"\b(?=[a-z0-9 .-]*\d)[a-z0-9][a-z0-9 .-]{4,}\b", candidate)
        if token:
            filters["serial_number"] = token.group(0).strip()
    elif enriched["intent_type"] == "lookup_equipment_by_code":
        match = re.search(r"\b([a-z]{1,4}-?\d{3,5})\b", text)
        if match:
            filters["equipment"] = match.group(1).upper()
    if filters.get("serial_number"):
        filters["serial_number"] = str(filters["serial_number"]).strip(" .?!,;:")
    if filters.get("equipment"):
        filters["equipment"] = str(filters["equipment"]).strip(" .?!,;:")
    enriched["filters"] = filters
    if enriched["intent_type"] in {
        "downtime_drivers", "affected_equipment", "downtime_events",
        "repeated_failures", "comment_analysis", "smcs_breakdown",
    } and enriched.get("metric") in {"downtime", "downtime_hours"}:
        enriched["metric"] = None
    enriched = enrich_fleet_performance_intent(enriched, question)
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
