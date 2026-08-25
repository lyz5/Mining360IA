from __future__ import annotations

import calendar
import re
from datetime import date, datetime

from django.db.models import Q
from django.urls import reverse
from django.urls.exceptions import NoReverseMatch

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
    "performance_overview",
    "equipment_detail",
    "downtime_drivers",
    "trend_analysis",
    "entity_comparison",
    "period_comparison",
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

METRIC_OPTIONAL_INTENT_TYPES = {
    "navigation", "follow_up_navigation", "powerbi_navigation",
    "performance_overview", "equipment_detail", "downtime_drivers",
    "affected_equipment", "downtime_events", "root_cause_analysis",
    "repeated_failures", "comment_analysis", "smcs_breakdown",
    "clarification_required",
}

MONTH_ABBREVIATIONS = (
    "",
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)


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


def _subtract_months(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 - months
    year, month_zero_based = divmod(month_index, 12)
    month = month_zero_based + 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def _period_navigation_range(value) -> tuple[date, date] | None:
    text = str(value or "").strip().lower()
    today = date.today()
    if text == "year to date":
        return date(today.year, 1, 1), today
    if text == "month to date":
        return date(today.year, today.month, 1), today
    if text == "last 12 months":
        return _subtract_months(today, 12), today
    if text in {"current month", "ce mois", "mois courant"}:
        return date(today.year, today.month, 1), date(
            today.year,
            today.month,
            calendar.monthrange(today.year, today.month)[1],
        )
    if text in {"previous month", "last month", "mois précédent", "mois precedent"}:
        previous = _subtract_months(date(today.year, today.month, 1), 1)
        return previous, date(
            previous.year,
            previous.month,
            calendar.monthrange(previous.year, previous.month)[1],
        )
    match = re.fullmatch(r"(20\d{2})", text)
    if match:
        year = int(match.group(1))
        return date(year, 1, 1), date(year, 12, 31)
    match = re.fullmatch(r"(20\d{2})-(\d{2})", text)
    if match:
        year, month = int(match.group(1)), int(match.group(2))
        return date(year, month, 1), date(
            year,
            month,
            calendar.monthrange(year, month)[1],
        )
    return None


def _year_month_filter_values(value) -> list[str] | None:
    text = str(value or "").strip()
    period_range = _period_navigation_range(value)
    if not period_range:
        return [text] if text else None
    start, end = period_range
    if text.casefold() == "last 12 months":
        start = _subtract_months(date(end.year, end.month, 1), 11)
    cursor = date(start.year, start.month, 1)
    final_month = date(end.year, end.month, 1)
    values = []
    while cursor <= final_month:
        values.append(f"{MONTH_ABBREVIATIONS[cursor.month]} {cursor.year}")
        next_month = cursor.month + 1
        next_year = cursor.year
        if next_month == 13:
            next_month = 1
            next_year += 1
        cursor = date(next_year, next_month, 1)
    return values


def is_follow_up_question(question_text: str) -> bool:
    text = re.sub(r"\s+", " ", str(question_text or "").strip().lower())
    if not text:
        return False
    confirmation_terms = (
        "are you sure", "can you confirm", "please confirm", "confirm that",
        "tu es sûr", "tu es sur", "êtes-vous sûr", "etes-vous sur",
        "peux-tu confirmer", "pouvez-vous confirmer", "confirme",
        "c'est bien", "est-ce bien", "est ce bien",
    )
    if any(term in text for term in confirmation_terms):
        return True
    explicit_follow_up = (
        "and ", "and for ", "what about ", "how about ", "same for ",
        "show me the details", "show details", "more details",
        "et ", "et pour ", "qu'en est-il", "même chose pour",
        "meme chose pour", "montre les détails", "plus de détails",
    )
    if any(text.startswith(prefix) for prefix in explicit_follow_up):
        return True
    explicit_request = (
        "give me ", "what is ", "what's ", "show me ",
        "donne-moi ", "donne moi ", "quelle est ", "quel est ",
        "affiche ", "montre-moi ", "montre moi ",
    )
    if any(text.startswith(prefix) for prefix in explicit_request):
        return False
    metric_terms = (
        "availability", "physical availability",
        "disponibilité", "disponibilite", "dispo",
    )
    if any(term in text for term in metric_terms):
        return False
    return len(text.split()) <= 5


def merge_conversation_intent(
    intent: dict,
    previous_intent: dict | None,
    *,
    inherit_previous: bool = True,
) -> dict:
    previous = (
        previous_intent
        if inherit_previous and isinstance(previous_intent, dict)
        else {}
    )
    merged = {
        "section": intent.get("section") or previous.get("section"),
        "intent_type": intent.get("intent_type") or "single_kpi",
        "metric": intent.get("metric") or previous.get("metric"),
        "filters": dict(previous.get("filters") or {}),
        "comparison": intent.get("comparison", previous.get("comparison")),
        "navigation": dict(intent.get("navigation") or {}),
        "root_cause_context": (
            intent.get("root_cause_context")
            or previous.get("root_cause_context")
        ),
    }
    for field in (
        "domain", "scope_type", "primary_metric", "secondary_metrics", "group_by",
        "ranking", "diagnostic_request", "root_cause_request", "navigation_request",
        "requires_clarification", "clarification_question", "query_intent_type",
    ):
        value = intent.get(field, previous.get(field))
        if value is not None:
            merged[field] = value
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
    if intent_type not in METRIC_OPTIONAL_INTENT_TYPES or metric_code:
        metrics = {
            item["metric_code"] for item in get_metric_mapping(section.code)
            if item.get("is_active")
        }
        if metric_code and metric_code not in metrics:
            errors.append(f"Metric '{metric_code or '(missing)'}' is not configured for section '{section.code}'.")
        elif not metric_code and intent_type not in METRIC_OPTIONAL_INTENT_TYPES:
            errors.append(f"Metric '(missing)' is not configured for section '{section.code}'.")

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
    return ["Validated", "Draft", "To Review", "Imported"] if debug_mode else ["Validated"]


def _mapped_slicer_values(slicer: PowerBISlicer | None, values: list) -> list:
    if not slicer or not isinstance(slicer.value_mapping, dict):
        return values
    normalized_mapping = {
        str(source).strip().casefold(): target
        for source, target in slicer.value_mapping.items()
    }
    return [
        normalized_mapping.get(str(value).strip().casefold(), value)
        for value in values
    ]


def _resolve_page_filters(
    *,
    page: PowerBIPage | None,
    raw_filters: dict,
    filter_config: dict,
    statuses: list[str],
) -> list[dict]:
    slicers = {
        item.filter_code: item
        for item in PowerBISlicer.objects.filter(
            page=page,
            is_active=True,
            validation_status__in=statuses,
        )
    } if page else {}
    resolved_filters = []
    for code, raw_value in raw_filters.items():
        mapping = filter_config.get(code)
        if not mapping or raw_value in (None, "", []):
            continue
        value = _sanitize_filter_value(raw_value)
        values = value if isinstance(value, list) else [value]
        slicer = slicers.get(code)
        values = _mapped_slicer_values(slicer, values)
        period_range = _period_navigation_range(value) if code == "period" else None
        is_year_month_slicer = bool(
            slicer
            and re.sub(r"[^a-z0-9]", "", slicer.powerbi_column_name.casefold())
            == "yearmonth"
        )
        if code == "period" and is_year_month_slicer:
            values = _year_month_filter_values(value) or values
            period_range = None
        instruction = {
            "filter_code": code,
            "table": slicer.powerbi_table_name if slicer else mapping["powerbi_table_name"],
            "column": slicer.powerbi_column_name if slicer else mapping["powerbi_column_name"],
            "data_type": slicer.data_type if slicer else mapping.get("data_type", "Text"),
            "operator": "In",
            "values": values,
            "scope": "slicer" if slicer else "page",
            "slicer_internal_name": slicer.slicer_internal_name if slicer else "",
        }
        if period_range:
            instruction.update({
                "column": "Date",
                "filter_type": "advanced",
                "conditions": [
                    {"operator": "GreaterThanOrEqual", "value": period_range[0].isoformat()},
                    {"operator": "LessThanOrEqual", "value": period_range[1].isoformat()},
                ],
                "scope": "page",
                "slicer_internal_name": "",
            })
        resolved_filters.append(instruction)
    return resolved_filters


def resolve_navigation(intent: dict, debug_mode: bool = False) -> dict:
    section = get_section_by_code(intent.get("section"))
    if not section:
        raise PowerBIInteractionError("A valid section is required for navigation.")
    metric_code = str(intent.get("metric") or "").strip()
    intent_type = str(intent.get("intent_type") or "single_kpi").strip()
    statuses = _allowed_statuses(debug_mode)
    requested_navigation = intent.get("navigation") or {}

    report = None
    report_query = re.sub(
        r"[^a-z0-9]+",
        " ",
        str(requested_navigation.get("report_query") or "").casefold(),
    ).strip()
    requested_report_id = str(requested_navigation.get("report_id") or "").strip()
    if requested_report_id:
        report = PowerBIReport.objects.filter(
            report_id=requested_report_id,
            is_active=True,
            validation_status__in=statuses,
        ).first()
    elif report_query:
        matches = []
        for candidate in PowerBIReport.objects.filter(
            is_active=True,
            validation_status__in=statuses,
        ):
            names = {
                re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
                for value in (candidate.report_name, candidate.display_name)
                if value
            }
            score = max((len(name) for name in names if name and name in report_query), default=0)
            if score:
                matches.append((score, candidate))
        if matches:
            report = max(matches, key=lambda item: item[0])[1]

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
    report = report or (intent_mapping.report if intent_mapping else None)
    mapping_matches_report = bool(intent_mapping and intent_mapping.report_id == getattr(report, "pk", None))
    page = intent_mapping.page if mapping_matches_report else None
    visual = intent_mapping.visual if mapping_matches_report else None
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
    raw_filters = intent.get("filters") or {}
    resolved_filters = _resolve_page_filters(
        page=page,
        raw_filters=raw_filters,
        filter_config=filter_config,
        statuses=statuses,
    )

    warnings = []
    if requested_navigation.get("open_page") and not page:
        warnings.append("No validated page mapping was found; the report default page will be used.")
    if requested_navigation.get("focus_visual") and not visual:
        warnings.append("No validated visual mapping was found; the page will open without visual focus.")
    alternative_reports = []
    alternative_mappings = (
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
        .exclude(report=report, page=page)
        .order_by("priority", "-is_default")
    )
    for mapping in alternative_mappings:
        alternative_reports.append({
            "report_id": mapping.report.report_id,
            "report_name": mapping.report.report_name,
            "display_name": mapping.report.display_name,
            "semantic_model_id": mapping.report.semantic_model_id,
            "embed_url": mapping.report.embed_url,
            "page_internal_name": mapping.page.page_internal_name,
            "page_display_name": mapping.page.page_display_name,
            "filters": _resolve_page_filters(
                page=mapping.page,
                raw_filters=raw_filters,
                filter_config=filter_config,
                statuses=statuses,
            ),
            "visual_internal_name": "",
            "visual_action": "",
            "warnings": ["No validated visual mapping was found; the page will open without visual focus."],
            "launch_mode": mapping.report.launch_mode,
            "launch_url": _report_launch_url(mapping.report),
        })
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
        "launch_mode": report.launch_mode,
        "launch_url": _report_launch_url(report),
        "alternative_reports": alternative_reports,
        "_objects": {"report": report, "page": page, "visual": visual},
    }


def public_navigation_payload(payload: dict) -> dict:
    return {key: value for key, value in payload.items() if key != "_objects"}


def _report_launch_url(report) -> str:
    try:
        return reverse("report-detail", args=[report.report_id])
    except NoReverseMatch:
        # Imported legacy/test configurations may not yet contain a Power BI UUID.
        return ""
