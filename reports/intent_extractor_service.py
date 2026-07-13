from __future__ import annotations

import re

from .ai_config_service import build_section_catalog, get_active_sections, get_section_by_code
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
    match = re.search(r"\b(20\d{2})[-/](\d{1,2})\b", text)
    if match:
        return f"{match.group(1)}-{int(match.group(2)):02d}"
    for month_name, month_number in MONTH_ALIASES.items():
        if re.search(rf"\b{re.escape(month_name)}\b", text):
            year_match = re.search(r"\b(20\d{2})\b", text)
            if year_match:
                return f"{year_match.group(1)}-{month_number}"
    if "last 12 months" in text or "douze derniers mois" in text or "12 derniers mois" in text:
        return "last 12 months"
    return None


def _extract_value(question_text: str, entity_type: str) -> str | None:
    text = str(question_text or "")
    lowered = text.lower()
    if entity_type == "minesite":
        match = re.search(r"(?:minesite|mine ?site|site)\s*[:=]\s*([a-z0-9 /_-]+)", text, re.I)
        if match:
            return match.group(1).strip()
    if entity_type == "model":
        match = re.search(r"(?:model|mod[eè]le)\s*[:=]?\s*([a-z0-9. -]+)", text, re.I)
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
        match = re.search(r"(?:family|famille)\s*[:=]\s*([a-z0-9 /_-]+)", text, re.I)
        if match:
            return match.group(1).strip()
    if entity_type == "field":
        match = re.search(r"(?:field|champ)\s*[:=]\s*([a-z0-9 /_-]+)", text, re.I)
        if match:
            return match.group(1).strip()
    return None


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
    if section == "performance" and not metric and any(filters.get(key) for key in ("minesite", "model", "family", "serial_number", "period", "customer")):
        metric = "availability"
    return {
        "section": section,
        "intent_type": "single_kpi",
        "metric": metric,
        "filters": filters,
        "comparison": None,
        "navigation": {"open_report": True, "open_page": True, "focus_visual": True},
    }


def extract_intent(question_text: str, section_code: str | None = None) -> dict:
    fallback = _build_fallback_intent(question_text, section_code)
    try:
        extracted = openai_extract_intent(question_text, section_code or fallback["section"])
        if extracted.get("section"):
            fallback["section"] = extracted["section"]
        if extracted.get("metric") is not None:
            fallback["metric"] = extracted["metric"]
        if extracted.get("intent_type"):
            fallback["intent_type"] = extracted["intent_type"]
        if isinstance(extracted.get("filters"), dict):
            fallback["filters"].update(extracted["filters"])
        if isinstance(extracted.get("navigation"), dict):
            fallback["navigation"].update(extracted["navigation"])
        fallback["comparison"] = extracted.get("comparison", fallback.get("comparison"))
    except Exception:
        pass
    return fallback
