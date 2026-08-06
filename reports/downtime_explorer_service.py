from __future__ import annotations

from .downtime_comment_analysis_service import analyze_comments
from .downtime_context_service import serialize_session
from .downtime_event_service import (
    comment_coverage,
    detect_repeated_failures,
    normalize_events,
)
from .downtime_query_service import (
    available_dimensions,
    build_breakdown_dax,
    build_equipment_dax,
    build_events_dax,
    build_summary_dax,
    execute_explorer_dax,
)
from .models import KnowledgeRecommendedAction
from .powerbi_interaction_service import (
    public_navigation_payload,
    resolve_navigation,
)
from .smcs_service import resolve_event_smcs


def _clean_row(row: dict) -> dict:
    cleaned = {}
    for key, value in row.items():
        name = str(key)
        if "[" in name and name.endswith("]"):
            name = name.rsplit("[", 1)[-1][:-1]
        cleaned[name] = value
    return cleaned


def initial_payload(session, created: bool) -> dict:
    return {
        **serialize_session(session),
        "created": created,
        "summary": {},
        "breakdowns": [],
        "available_dimensions": available_dimensions(),
        "equipment": [],
        "events": [],
        "comment_coverage": {},
        "ai_analysis_status": "not_started",
        "available_actions": [
            "View Equipment",
            "View Events",
            "Analyze Comments",
            "Repeated Failures",
            "Open Power BI",
            "Reset Deep Dive",
            "Back to Pareto",
        ],
        "limitations": [
            "Component, Subcomponent and Cause are not mapped in the current semantic model."
        ],
    }


def load_summary(session) -> dict:
    result = execute_explorer_dax(
        session,
        level="summary",
        dax=build_summary_dax(session),
    )
    summary = _clean_row(result["rows"][0]) if result["rows"] else {}
    return {
        "summary": summary,
        "cached": result["cached"],
        "execution_time_ms": result["execution_time_ms"],
    }


def load_breakdown(session, dimension_code: str) -> dict:
    result = execute_explorer_dax(
        session,
        level=f"breakdown:{dimension_code}",
        dax=build_breakdown_dax(session, dimension_code),
    )
    return {
        "dimension": dimension_code,
        "rows": [_clean_row(row) for row in result["rows"]],
        "cached": result["cached"],
        "execution_time_ms": result["execution_time_ms"],
    }


def load_equipment(session) -> dict:
    result = execute_explorer_dax(
        session,
        level="equipment",
        dax=build_equipment_dax(session),
    )
    return {
        "rows": [_clean_row(row) for row in result["rows"]],
        "cached": result["cached"],
        "execution_time_ms": result["execution_time_ms"],
    }


def load_events(session, *, limit: int = 300) -> dict:
    result = execute_explorer_dax(
        session,
        level=f"events:{limit}",
        dax=build_events_dax(session, limit=limit),
    )
    events = normalize_events(result["rows"])
    return {
        "rows": events,
        "coverage": comment_coverage(events),
        "cached": result["cached"],
        "execution_time_ms": result["execution_time_ms"],
    }


def load_comments(session) -> dict:
    result = load_events(session, limit=300)
    comments = [
        item for item in result["rows"]
        if item.get("Comment")
    ]
    return {
        "rows": comments,
        "coverage": result["coverage"],
        "cached": result["cached"],
        "execution_time_ms": result["execution_time_ms"],
    }


def load_repeated_failures(session, window_days: int = 90) -> dict:
    result = load_events(session, limit=500)
    repeated = detect_repeated_failures(
        result["rows"],
        window_days=window_days,
    )
    return {
        **repeated,
        "coverage": result["coverage"],
        "cached": result["cached"],
    }


def load_smcs_breakdown(session) -> dict:
    result = load_events(session, limit=500)
    breakdown = resolve_event_smcs(result["rows"])
    return {
        **breakdown,
        "cached": result["cached"],
        "event_coverage": result["coverage"],
    }


def run_comment_analysis(session) -> dict:
    events_result = load_events(session, limit=300)
    analysis = analyze_comments(session, events_result["rows"])
    return {
        "analysis_id": str(analysis.id),
        "status": analysis.status,
        "result": analysis.result_json,
        "execution_time_ms": analysis.execution_time_ms,
        "model": analysis.model_name,
        "prompt_version": analysis.prompt_version,
    }


def suggested_actions(session) -> list[dict]:
    configured = KnowledgeRecommendedAction.objects.filter(
        section__code="performance",
        kpi="availability",
        validation_status="Validated",
        is_active=True,
    ).order_by("priority")
    return [
        {
            "title": "Business recommendation",
            "recommendation": item.recommended_action,
            "context": item.business_context,
            "condition": item.condition,
            "priority": item.priority,
            "source": "Knowledge Base",
            "requires_validation": True,
        }
        for item in configured
    ]


def navigation_payload(session) -> dict:
    filters = dict(session.context_json.get("filters") or {})
    filters["downtime_driver"] = session.selected_driver
    intent = {
        "section": "performance",
        "intent_type": "single_kpi",
        "metric": "availability",
        "filters": filters,
        "navigation": {
            "open_report": True,
            "open_page": True,
            "focus_visual": True,
        },
    }
    return public_navigation_payload(resolve_navigation(intent))
