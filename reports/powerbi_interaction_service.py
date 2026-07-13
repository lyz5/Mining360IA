from __future__ import annotations

import re
from datetime import date, datetime

from django.db.models import Q

from .ai_config_service import get_filter_mapping, get_metric_mapping, get_section_by_code
from .models import (
    IntentNavigationMapping,
    KPIPageMapping,
    KPIVisualMapping,
    PowerBIPage,
    PowerBIReport,
    PowerBISlicer,
)


class PowerBIInteractionError(RuntimeError):
    pass


SAFE_INTENT_TYPES = {
    "single_kpi",
    "trend",
    "comparison",
    "ranking",
    "navigation",
    "follow_up_navigation",
}


def _sanitize_filter_value(value):
    if value is None:
        return None
    if isinstance(value, (date, datetime, int, float, bool)):
        return value.isoformat() if isinstance(value, (date, datetime)) else value
    if isinstance(value, list):
        if len(value) > 100:
            raise PowerBIInteractionError("A filter cannot contain more than 100 values.")
        return [_sanitize_filter_value(item) for item in value]
    text = re.sub(r"[\x00-\x1f\x7f]", "", str(value)).strip()
    if len(text) > 500:
        raise PowerBIInteractionError("A filter value is too long.")
    return text


def merge_conversation_intent(intent: dict, previous_intent: dict | None) -> dict:
    previous = previous_intent if isinstance(previous_intent, dict) else {}
    merged = {
        "section": intent.get("section") or previous.get("section"),
        "intent_type": intent.get("intent_type") or "single_kpi",
        "metric": intent.get("metric") or previous.get("metric"),
        "filters": dict(previous.get("filters") or {}),
        "comparison": intent.get("comparison", previous.get("comparison")),
        "navigation": dict(intent.get("navigation") or {}),
    }
    merged["filters"].update({
        key: value for key, value in (intent.get("filters") or {}).items()
        if value not in (None, "", [])
    })
    if merged["intent_type"] not in SAFE_INTENT_TYPES:
        merged["intent_type"] = "single_kpi"
    return merged


def validate_interaction_intent(intent: dict, debug_mode: bool = False) -> tuple[bool, list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    section = get_section_by_code(intent.get("section"))
    if not section:
        return False, ["Section does not exist or is inactive."], warnings

    metric_code = str(intent.get("metric") or "").strip()
    intent_type = str(intent.get("intent_type") or "single_kpi").strip()
    if intent_type not in SAFE_INTENT_TYPES:
        errors.append(f"Intent type '{intent_type}' is not supported.")
    if intent_type not in {"navigation", "follow_up_navigation"} or metric_code:
        metrics = {
            item["metric_code"] for item in get_metric_mapping(section.code)
            if item.get("is_active")
        }
        if not metric_code or metric_code not in metrics:
            errors.append(f"Metric '{metric_code or '(missing)'}' is not configured for section '{section.code}'.")

    configured_filters = {
        item["filter_code"]: item for item in get_filter_mapping(section.code)
        if item.get("is_active")
    }
    filters = intent.get("filters") or {}
    if not isinstance(filters, dict):
        errors.append("Filters must be an object.")
        return False, errors, warnings
    for code, value in filters.items():
        if code not in configured_filters:
            errors.append(f"Filter '{code}' is not configured for section '{section.code}'.")
            continue
        try:
            _sanitize_filter_value(value)
        except PowerBIInteractionError as exc:
            errors.append(str(exc))
    for code, mapping in configured_filters.items():
        if mapping.get("is_required") and filters.get(code) in (None, "", []):
            errors.append(f"Required filter '{code}' is missing.")

    navigation = intent.get("navigation") or {}
    if navigation.get("open_report"):
        try:
            resolve_navigation(intent, debug_mode=debug_mode)
        except PowerBIInteractionError as exc:
            errors.append(str(exc))
    return not errors, errors, warnings


def _allowed_statuses(debug_mode: bool) -> list[str]:
    return ["Validated", "To Review", "Imported"] if debug_mode else ["Validated"]


def resolve_navigation(intent: dict, debug_mode: bool = False) -> dict:
    section = get_section_by_code(intent.get("section"))
    if not section:
        raise PowerBIInteractionError("A valid section is required for navigation.")
    metric_code = str(intent.get("metric") or "").strip()
    intent_type = str(intent.get("intent_type") or "single_kpi").strip()
    statuses = _allowed_statuses(debug_mode)

    intent_mapping = (
        IntentNavigationMapping.objects
        .select_related("report", "page", "visual")
        .filter(section=section, intent_type=intent_type, is_active=True)
        .filter(Q(metric_code=metric_code) | Q(metric_code=""))
        .filter(report__is_active=True, report__validation_status__in=statuses)
        .order_by("priority", "-metric_code")
        .first()
    )
    page_mapping = None
    report = intent_mapping.report if intent_mapping else None
    page = intent_mapping.page if intent_mapping else None
    visual = intent_mapping.visual if intent_mapping else None
    visual_action = "focus"

    if not report:
        page_mapping = (
            KPIPageMapping.objects
            .select_related("report", "page")
            .filter(
                section=section,
                metric_code=metric_code,
                is_active=True,
                report__is_active=True,
                report__validation_status__in=statuses,
                page__is_active=True,
                page__validation_status__in=statuses,
            )
            .order_by("priority", "-is_default")
            .first()
        )
        if page_mapping:
            report, page = page_mapping.report, page_mapping.page
    if not report:
        report = (
            PowerBIReport.objects
            .filter(section=section, is_active=True, validation_status__in=statuses)
            .order_by("-is_default", "display_name")
            .first()
        )
    if not report:
        raise PowerBIInteractionError(f"No validated Power BI report is mapped to section '{section.code}'.")
    if not page:
        page = (
            PowerBIPage.objects
            .filter(report=report, is_active=True, validation_status__in=statuses)
            .order_by("-is_default", "page_order")
            .first()
        )

    requested_navigation = intent.get("navigation") or {}
    if requested_navigation.get("focus_visual") and not visual and page:
        visual_mapping = (
            KPIVisualMapping.objects
            .select_related("visual")
            .filter(
                section=section,
                metric_code=metric_code,
                page=page,
                is_active=True,
                visual__is_active=True,
                visual__validation_status__in=statuses,
            )
            .order_by("priority", "-is_default")
            .first()
        )
        if visual_mapping:
            visual = visual_mapping.visual
            visual_action = visual_mapping.interaction_action

    filter_config = {
        item["filter_code"]: item for item in get_filter_mapping(section.code)
        if item.get("is_active")
    }
    slicers = {
        item.filter_code: item
        for item in PowerBISlicer.objects.filter(
            page=page,
            is_active=True,
            validation_status__in=statuses,
        )
    } if page else {}
    resolved_filters = []
    for code, raw_value in (intent.get("filters") or {}).items():
        mapping = filter_config.get(code)
        if not mapping or raw_value in (None, "", []):
            continue
        value = _sanitize_filter_value(raw_value)
        values = value if isinstance(value, list) else [value]
        slicer = slicers.get(code)
        resolved_filters.append({
            "filter_code": code,
            "table": slicer.powerbi_table_name if slicer else mapping["powerbi_table_name"],
            "column": slicer.powerbi_column_name if slicer else mapping["powerbi_column_name"],
            "data_type": slicer.data_type if slicer else mapping.get("data_type", "Text"),
            "operator": "In",
            "values": values,
            "scope": "slicer" if slicer else "page",
            "slicer_internal_name": slicer.slicer_internal_name if slicer else "",
        })

    warnings = []
    if requested_navigation.get("open_page") and not page:
        warnings.append("No validated page mapping was found; the report default page will be used.")
    if requested_navigation.get("focus_visual") and not visual:
        warnings.append("No validated visual mapping was found; the page will open without visual focus.")
    return {
        "report_id": report.report_id,
        "report_name": report.report_name,
        "display_name": report.display_name,
        "semantic_model_id": report.semantic_model_id,
        "embed_url": report.embed_url,
        "page_internal_name": page.page_internal_name if page else "",
        "page_display_name": page.page_display_name if page else "",
        "filters": resolved_filters,
        "visual_internal_name": visual.visual_internal_name if visual else "",
        "visual_action": visual_action if visual else "",
        "warnings": warnings,
        "_objects": {"report": report, "page": page, "visual": visual},
    }


def public_navigation_payload(payload: dict) -> dict:
    return {key: value for key, value in payload.items() if key != "_objects"}
