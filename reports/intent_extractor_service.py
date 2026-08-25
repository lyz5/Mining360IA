from __future__ import annotations

from datetime import date
import re

from .ai_config_service import build_section_catalog, get_active_sections, get_section_by_code
from .machine_performance_intent_service import (
    detect_machine_performance_intent,
    enrich_machine_performance_intent,
)
from .openai_service import extract_intent as openai_extract_intent


MONTH_ALIASES = {
    "janvier": "01",
    "january": "01",
    "février": "02",
    "fevrier": "02",
    "february": "02",
    "mars": "03",
    "march": "03",
    "avril": "04",
    "april": "04",
    "mai": "05",
    "may": "05",
    "juin": "06",
    "june": "06",
    "juillet": "07",
    "july": "07",
    "août": "08",
    "aout": "08",
    "august": "08",
    "septembre": "09",
    "september": "09",
    "octobre": "10",
    "october": "10",
    "novembre": "11",
    "november": "11",
    "décembre": "12",
    "decembre": "12",
    "december": "12",
}


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _detect_section(question_text: str, section_code: str | None = None) -> str:
    if section_code and get_section_by_code(section_code):
        return section_code
    text = _normalize(question_text)
    if any(token in text for token in ("parts sales", "part sales", "sales amount", "part number", "margin")):
        return "parts_sales"
    if any(token in text for token in ("rebuild", "component", "planned component")):
        return "planned_component_rebuild"
    return "performance"


def _detect_metric(question_text: str, section_code: str) -> str | None:
    text = _normalize(question_text)
    catalog = build_section_catalog(section_code).get("sections", [])
    if not catalog:
        return None
    section = catalog[0]
    candidates = section.get("metrics", [])
    if section_code == "performance" and any(token in text for token in ("downtime", "down time", "arrêt", "arret")) and any(
        token in text for token in ("hour", "hours", "heure", "heures", "nombre d heure", "nombre d'heures")
    ):
        if any(item.get("metric_code") == "downtime_hours" for item in candidates):
            return "downtime_hours"
    metric_tokens = []
    for metric in candidates:
        metric_tokens.append((metric.get("metric_code", ""), metric.get("metric_label", "")))
    for code, label in metric_tokens:
        code_norm = _normalize(code)
        label_norm = _normalize(label)
        if code_norm and code_norm in text:
            return code
        if label_norm and label_norm in text:
            return code
    synonyms = section.get("synonyms", [])
    for item in synonyms:
        if item.get("entity_type") != "metric":
            continue
        if _normalize(item.get("synonym_value")) in text or _normalize(item.get("canonical_value")) in text:
            return item.get("canonical_value")
    if section_code == "performance":
        availability_tokens = (
            "availability",
            "disponibilité",
            "disponibilite",
            "dispo",
            "physical availability",
            "pa",
        )
        if any(token in text for token in availability_tokens):
            return "availability"
        for fallback in ("availability", "physical_availability", "mtbf", "mttr", "mtbs", "downtime", "idle_time", "fuel_burn"):
            if fallback in text:
                return fallback
    return None


def _extract_period(question_text: str) -> str | None:
    text = _normalize(question_text)
    relative_periods = (
        (
            "year to date",
            (
                "year to date", "year-to-date", "ytd",
                "cumul annuel", "depuis le début de l'année",
                "depuis le debut de l'annee", "année à date", "annee a date",
            ),
        ),
        (
            "month to date",
            (
                "month to date", "month-to-date", "mtd",
                "cumul mensuel", "depuis le début du mois",
                "depuis le debut du mois", "mois à date", "mois a date",
            ),
        ),
        (
            "last 12 months",
            (
                "last 12 months", "last twelve months", "l12m",
                "rolling 12 months", "trailing 12 months",
                "douze derniers mois", "12 derniers mois",
                "12 mois glissants", "douze mois glissants",
            ),
        ),
    )
    for canonical_value, aliases in relative_periods:
        if any(re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text) for alias in aliases):
            return canonical_value
    match = re.search(r"\b(20\d{2})[-/](\d{1,2})\b", text)
    if match:
        return f"{match.group(1)}-{int(match.group(2)):02d}"
    for month_name, month_number in MONTH_ALIASES.items():
        if re.search(rf"\b{re.escape(month_name)}\b", text):
            year_match = re.search(r"\b(20\d{2})\b", text)
            year = year_match.group(1) if year_match else str(date.today().year)
            return f"{year}-{month_number}"
    if "current month" in text or "ce mois" in text or "mois courant" in text:
        return "current month"
    if "previous month" in text or "last month" in text or "mois précédent" in text or "mois precedent" in text:
        return "previous month"
    year_match = re.search(r"\b(20\d{2})\b", text)
    if year_match:
        return year_match.group(1)
    return None


def _extract_value(question_text: str, entity_type: str) -> str | None:
    text = str(question_text or "")
    lowered = text.lower()
    if entity_type == "minesite":
        match = re.search(r"(?:minesite|mine ?site|site)\s*[:=]\s*([a-z0-9 /_-]+)", text, re.I)
        if match:
            return match.group(1).strip()
    if entity_type == "model":
        match = re.search(
            r"(?:model\b|mod[eè]le\b)\s*[:=]?\s*([a-z0-9][a-z0-9./_-]*)",
            text,
            re.I,
        )
        if match:
            return match.group(1).strip().upper()
        match = re.search(r"\b(6015|6020|6030|6040|6050|777 wt|777|785|789|d10|d9|992|390|395|980|988|844)\b", lowered, re.I)
        if match:
            return match.group(1).strip().upper()
    if entity_type == "period":
        return _extract_period(text)
    if entity_type == "customer":
        match = re.search(r"(?:customer|client)\s*[:=]\s*([a-z0-9 /_-]+)", text, re.I)
        if match:
            return match.group(1).strip()
    if entity_type == "component":
        match = re.search(r"(?:component|composant)\s*[:=]\s*([a-z0-9 /_-]+)", text, re.I)
        if match:
            return match.group(1).strip()
    if entity_type == "family":
        match = re.search(
            r"(?:family|famille)\s*[:=]?\s*([a-z0-9][a-z0-9 /_-]*?)"
            r"(?=\s*(?:,|;|\?|$|\b(?:at|in|for|pour|au|à|site|minesite|model|mod[eè]le|period|p[eé]riode|serial|sn)\b))",
            text,
            re.I,
        )
        if match:
            return match.group(1).strip()
    if entity_type == "serial_number":
        match = re.search(
            r"(?:serial(?:\s+number)?|num[eé]ro\s+de\s+s[eé]rie|\bsn\b)"
            r"\s*[:=]?\s*([a-z0-9][a-z0-9./_-]*)",
            text,
            re.I,
        )
        if match:
            return match.group(1).strip().upper()
        match = re.search(
            r"(?:machine|equipment|[eé]quipement)\s+([a-z0-9][a-z0-9./_-]*\d[a-z0-9./_-]*)",
            text,
            re.I,
        )
        if match:
            return match.group(1).strip().upper()
    if entity_type == "field":
        match = re.search(r"(?:field|champ)\s*[:=]\s*([a-z0-9 /_-]+)", text, re.I)
        if match:
            return match.group(1).strip()
    return None


def _detect_intent_type(question_text: str) -> str:
    return detect_machine_performance_intent(question_text)


def _ranking_payload(question_text: str) -> dict | None:
    if _detect_intent_type(question_text) != "ranking":
        return None
    text = _normalize(question_text)
    dimension = "model"
    if any(token in text for token in ("site", "minesite", "mine site")):
        dimension = "minesite"
    elif any(token in text for token in ("machine", "equipment", "serial", "équipement", "equipement")):
        dimension = "serial_number"
    top_match = re.search(r"\b(?:top|bottom)\s+(\d{1,2})\b", text)
    return {
        "dimension": dimension,
        "direction": "desc" if any(token in text for token in ("highest", "top ", "meilleur", "plus élevé", "plus eleve")) else "asc",
        "top_n": min(int(top_match.group(1)), 50) if top_match else 10,
    }


def _build_fallback_intent(question_text: str, section_code: str | None = None) -> dict:
    section = _detect_section(question_text, section_code)
    catalog = build_section_catalog(section).get("sections", [])
    section_payload = catalog[0] if catalog else {}
    metric = _detect_metric(question_text, section)
    filters = {}
    for filter_mapping in section_payload.get("filters", []):
        code = filter_mapping.get("filter_code")
        value = _extract_value(question_text, code)
        if value:
            filters[code] = value
    if "period" in [item.get("filter_code") for item in section_payload.get("filters", [])]:
        period_value = _extract_period(question_text)
        if period_value:
            filters["period"] = period_value
    intent = {
        "section": section,
        "intent_type": _detect_intent_type(question_text),
        "metric": metric,
        "filters": filters,
        "comparison": _ranking_payload(question_text),
        "navigation": {"open_report": True, "open_page": True, "focus_visual": True},
    }
    if intent["intent_type"] == "powerbi_navigation":
        intent["navigation"]["report_query"] = str(question_text or "").strip()
    return enrich_machine_performance_intent(intent, question_text) if section == "performance" else intent


def extract_intent(question_text: str, section_code: str | None = None) -> dict:
    fallback = _build_fallback_intent(question_text, section_code)
    # Availability is fully controlled by configured synonyms, filters and DAX
    # templates. Avoid a slow and less deterministic LLM extraction when the
    # business intent is already resolved locally.
    if fallback.get("metric") == "availability" or fallback.get("intent_type") == "powerbi_navigation":
        return enrich_machine_performance_intent(fallback, question_text)
    try:
        extracted = openai_extract_intent(question_text, section_code or fallback["section"])
        if extracted.get("section"):
            fallback["section"] = extracted["section"]
        if extracted.get("metric") is not None:
            fallback["metric"] = extracted["metric"]
        if extracted.get("intent_type") and fallback["intent_type"] == "single_kpi":
            fallback["intent_type"] = extracted["intent_type"]
        if isinstance(extracted.get("filters"), dict):
            ai_filters = {
                key: value
                for key, value in extracted["filters"].items()
                if value not in (None, "", [])
            }
            deterministic_filters = dict(fallback["filters"])
            fallback["filters"] = ai_filters
            fallback["filters"].update(deterministic_filters)
        if isinstance(extracted.get("navigation"), dict):
            fallback["navigation"].update(extracted["navigation"])
        if fallback.get("comparison") is None:
            fallback["comparison"] = extracted.get("comparison")
    except Exception:
        pass
    fallback["filters"] = {
        key: value
        for key, value in fallback["filters"].items()
        if value not in (None, "", [])
    }
    if fallback.get("metric") == "physical_availability":
        fallback["metric"] = "availability"
    return enrich_machine_performance_intent(fallback, question_text) if fallback.get("section") == "performance" else fallback
