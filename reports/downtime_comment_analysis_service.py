from __future__ import annotations

import json
import time

from .downtime_event_service import comment_coverage
from .models import (
    DowntimeExplorerAIAnalysis,
    DowntimeExplorerSession,
    KnowledgePrompt,
    RootCauseTheme,
)
from .ai_provider_gateway_service import ai_gateway


REQUIRED_RESULT_KEYS = {
    "coverage",
    "themes",
    "repeated_patterns",
    "data_quality_findings",
    "summary",
    "limitations",
    "suggested_investigations",
}
ROOT_CAUSE_PROMPT_NAME = "Downtime Root Cause Comment Analysis"
ROOT_CAUSE_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "coverage": {
            "type": "object",
            "properties": {
                "event_count": {"type": "integer"},
                "commented_event_count": {"type": "integer"},
                "downtime_hours": {"type": "number"},
                "covered_downtime_hours": {"type": "number"},
                "coverage_percentage": {"type": "number"},
            },
            "required": [
                "event_count",
                "commented_event_count",
                "downtime_hours",
                "covered_downtime_hours",
                "coverage_percentage",
            ],
            "additionalProperties": False,
        },
        "themes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "classification": {"type": "string"},
                    "summary": {"type": "string"},
                    "event_count": {"type": "integer"},
                    "downtime_hours": {"type": "number"},
                    "affected_equipment": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "evidence_event_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "confidence": {"type": "number"},
                },
                "required": [
                    "name",
                    "classification",
                    "summary",
                    "event_count",
                    "downtime_hours",
                    "affected_equipment",
                    "evidence_event_ids",
                    "confidence",
                ],
                "additionalProperties": False,
            },
        },
        "repeated_patterns": {"type": "array", "items": {"type": "string"}},
        "data_quality_findings": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
        "limitations": {"type": "array", "items": {"type": "string"}},
        "suggested_investigations": {"type": "array", "items": {"type": "string"}},
    },
    "required": sorted(REQUIRED_RESULT_KEYS),
    "additionalProperties": False,
}


def _validate_result(result: dict) -> None:
    if not isinstance(result, dict) or not REQUIRED_RESULT_KEYS.issubset(result):
        missing = sorted(REQUIRED_RESULT_KEYS.difference(result or {}))
        detail = f" Missing keys: {', '.join(missing)}." if missing else ""
        raise ValueError(
            "The AI provider returned an invalid root cause analysis JSON." + detail
        )
    if not isinstance(result.get("themes"), list):
        raise ValueError("Root cause themes must be a list.")
    for theme in result["themes"]:
        if not isinstance(theme, dict):
            raise ValueError("Each root cause theme must be an object.")
        if not isinstance(theme.get("evidence_event_ids", []), list):
            raise ValueError("Theme evidence_event_ids must be a list.")


def analyze_comments(
    session: DowntimeExplorerSession,
    events: list[dict],
) -> DowntimeExplorerAIAnalysis:
    prompt = KnowledgePrompt.objects.filter(
        section__code="performance",
        prompt_name=ROOT_CAUSE_PROMPT_NAME,
        validation_status="Validated",
        is_active=True,
    ).order_by("-updated_at").first()
    if not prompt:
        raise RuntimeError(
            f"No validated {ROOT_CAUSE_PROMPT_NAME} prompt is configured."
        )
    themes = list(
        RootCauseTheme.objects.filter(
            section__code="performance",
            validation_status="Validated",
            is_active=True,
        ).values("code", "name", "description", "synonyms", "examples")
    )
    coverage = comment_coverage(events)
    commented_events = [
        {
            "event_id": item["Event ID"],
            "serial_number": item.get("Serial Number"),
            "equipment": item.get("Equipment"),
            "start_date": item.get("Start Date"),
            "duration_hours": item.get("Duration"),
            "driver": item.get("Downtime Driver"),
            "work_type": item.get("Work Type"),
            "labour_type": item.get("Labour Type"),
            "comment": str(item.get("Comment") or "")[:800],
        }
        for item in events
        if item.get("Comment")
    ][:100]
    if not commented_events:
        raise ValueError(
            "No comment is available for the selected downtime events. "
            "The analysis can continue with structured data only."
        )
    payload = {
        "rules": prompt.prompt_content,
        "configured_themes": themes,
        "context": session.context_json,
        "coverage_calculated_by_backend": coverage,
        "events": commented_events,
        "required_output": {
            "coverage": {},
            "themes": [],
            "repeated_patterns": [],
            "data_quality_findings": [],
            "summary": "",
            "limitations": [],
            "suggested_investigations": [],
        },
    }
    started = time.monotonic()
    analysis = DowntimeExplorerAIAnalysis.objects.create(
        session=session,
        context_json=session.context_json,
        event_ids=[item["event_id"] for item in commented_events],
        model_name="",
        prompt_version=prompt.version,
        status="Running",
        coverage_percentage=coverage["coverage_percentage"],
    )
    try:
        conversation_id = (
            session.conversation.conversation_id if session.conversation else ""
        )
        response = ai_gateway.generate_structured_output(
            use_case="root_cause_comment_analysis",
            messages=[
                {"role": "system", "content": prompt.prompt_content},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            output_schema=ROOT_CAUSE_OUTPUT_SCHEMA,
            context={
                "user": session.user,
                "conversation_id": conversation_id,
                "agent_code": "machine_performance",
            },
            options={"temperature": 0},
        )
        result = response.structured_output or {}
        _validate_result(result)
        # Coverage is authoritative from backend, not recalculated by the LLM.
        result["coverage"] = coverage
        analysis.model_name = response.model
        analysis.result_json = result
        analysis.input_tokens = int(response.usage.get("input_tokens", 0))
        analysis.output_tokens = int(response.usage.get("output_tokens", 0))
        analysis.status = "Completed"
    except Exception as exc:
        analysis.status = "Failed"
        analysis.error_message = str(exc)
        analysis.execution_time_ms = int((time.monotonic() - started) * 1000)
        analysis.save()
        raise
    analysis.execution_time_ms = int((time.monotonic() - started) * 1000)
    analysis.save()
    return analysis
