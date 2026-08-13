from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import OperationalError, ProgrammingError
from django.conf import settings

from .models import AIIntentResponseTemplateMapping, AIResponseTemplate


DEFAULT_TEMPLATES = {
    "single_kpi": ["primary_metric", "context", "contextual_actions"],
    "performance_overview": ["metric_grid", "key_takeaway", "contextual_actions"],
    "equipment_detail": ["equipment_identity", "metric_grid", "result_table", "contextual_actions"],
    "downtime_drivers": ["context", "downtime_summary", "key_takeaway", "downtime_drivers", "contextual_actions"],
    "entity_comparison": ["context", "comparison_summary", "comparison_table", "key_takeaway", "contextual_actions"],
    "period_comparison": ["context", "comparison_summary", "comparison_table", "key_takeaway", "contextual_actions"],
    "trend_analysis": ["context", "trend_summary", "trend_chart", "result_table", "contextual_actions"],
    "ranking": ["context", "ranking_table", "key_takeaway", "contextual_actions"],
    "affected_equipment": ["context", "equipment_table", "contextual_actions"],
    "downtime_events": ["context", "events_table", "contextual_actions"],
    "root_cause_analysis": ["context", "diagnostic_summary", "downtime_drivers", "evidence", "contextual_actions"],
    "repeated_failures": ["context", "repeated_failures", "result_table", "contextual_actions"],
    "comment_analysis": ["context", "comment_coverage", "evidence", "result_table", "contextual_actions"],
    "smcs_breakdown": ["context", "smcs_coverage", "result_table", "contextual_actions"],
    "powerbi_navigation": ["navigation_confirmation", "contextual_actions"],
    "generic_analytical": ["context", "result_table", "contextual_actions"],
    "legacy_availability_response": ["primary_metric", "context", "downtime_summary", "downtime_drivers", "contextual_actions"],
}

REQUIRED_DATA = {
    "single_kpi": ["metric_value"],
    "entity_comparison": ["multiple_rows"],
    "period_comparison": ["multiple_rows"],
    "trend_analysis": ["multiple_rows"],
    "ranking": ["rows"],
    "downtime_drivers": ["downtime_drivers"],
    "equipment_detail": ["equipment_identity"],
}

ACTIONS = {
    "single_kpi": ["show_trend", "compare", "show_downtime_drivers", "open_powerbi"],
    "downtime_drivers": ["explore_driver", "view_affected_equipment", "show_events", "show_pareto"],
    "entity_comparison": ["change_metric", "view_entity", "compare_drivers", "open_powerbi"],
    "period_comparison": ["show_trend", "compare_drivers", "open_powerbi"],
    "trend_analysis": ["compare_periods", "show_anomalies", "show_downtime_drivers"],
    "ranking": ["open_equipment", "change_ranking", "open_powerbi"],
    "equipment_detail": ["show_events", "analyze_comments", "repeated_failures", "open_powerbi"],
    "root_cause_analysis": ["view_evidence", "analyze_comments", "view_affected_equipment", "open_root_cause_explorer"],
    "affected_equipment": ["open_equipment", "show_events", "open_powerbi"],
    "downtime_events": ["view_event", "analyze_comments", "open_powerbi"],
    "comment_analysis": ["view_evidence", "view_affected_equipment", "show_events"],
    "smcs_breakdown": ["review_classifications", "show_events", "open_root_cause_explorer"],
    "generic_analytical": ["open_powerbi"],
}

ACTION_LABELS = {
    "show_trend": "Show trend", "compare": "Compare", "show_downtime_drivers": "View downtime drivers",
    "open_powerbi": "Open in Power BI", "explore_driver": "Explore a driver",
    "view_affected_equipment": "View affected equipment", "show_events": "Show events",
    "show_pareto": "Show Pareto", "change_metric": "Change metric", "view_entity": "View entity",
    "compare_drivers": "Compare drivers", "compare_periods": "Compare periods",
    "show_anomalies": "Show anomalies", "open_equipment": "Open equipment",
    "change_ranking": "Change ranking", "analyze_comments": "Analyze comments",
    "repeated_failures": "Repeated failures", "view_evidence": "View evidence",
    "open_root_cause_explorer": "Open Root Cause Explorer", "view_event": "View event",
    "review_classifications": "Review classifications",
}


@dataclass(frozen=True)
class ResponseTemplatePlan:
    code: str
    version: str
    components: list[str]
    required_fields: list[str]
    fallback: str
    warnings: list[str]


class MachinePerformanceResponseTemplateResolver:
    def resolve(self, intent: dict, result: dict) -> ResponseTemplatePlan:
        if intent.get("_adaptive_responses_enabled") is False:
            return ResponseTemplatePlan(
                code="legacy_availability_response", version="legacy",
                components=DEFAULT_TEMPLATES["legacy_availability_response"],
                required_fields=[], fallback="generic_analytical", warnings=[],
            )
        intent_type = str(intent.get("intent_type") or "generic_analytical")
        scope_type = str(intent.get("scope_type") or "")
        metric = str(intent.get("primary_metric") or intent.get("metric") or "")
        template = None
        try:
            mappings = AIIntentResponseTemplateMapping.objects.select_related("response_template").filter(
                domain="machine_performance",
                intent_type=intent_type,
                active=True,
                validation_status="Validated",
                response_template__active=True,
                response_template__validation_status="Validated",
            )
            candidates = list(mappings.order_by("-priority"))
            candidates.sort(key=lambda item: (
                item.scope_type == scope_type,
                item.metric_code == metric,
                not item.scope_type,
                not item.metric_code,
                item.priority,
            ), reverse=True)
            template = next((item.response_template for item in candidates if
                (not item.scope_type or item.scope_type == scope_type)
                and (not item.metric_code or item.metric_code == metric)
            ), None)
            if template is None:
                template = AIResponseTemplate.objects.filter(
                    code=intent_type,
                    domain="machine_performance",
                    active=True,
                    validation_status="Validated",
                ).first()
        except (OperationalError, ProgrammingError):
            template = None

        code = template.code if template else (intent_type if intent_type in DEFAULT_TEMPLATES else "generic_analytical")
        components = list(template.component_order_json if template else DEFAULT_TEMPLATES[code])
        required = list(
            (template.required_data_fields_json or REQUIRED_DATA.get(code, []))
            if template else REQUIRED_DATA.get(code, [])
        )
        fallback = (template.fallback_template_code if template else "generic_analytical") or "generic_analytical"
        available = _available_data_fields(intent, result)
        missing = [field for field in required if field not in available]
        warnings = [f"Partial data: missing {field}." for field in missing]
        if missing and code in {"entity_comparison", "period_comparison", "trend_analysis"}:
            code = fallback
            components = DEFAULT_TEMPLATES.get(code, DEFAULT_TEMPLATES["generic_analytical"])
        return ResponseTemplatePlan(
            code=code,
            version=template.version if template else "1.0",
            components=components,
            required_fields=required,
            fallback=fallback,
            warnings=warnings,
        )


class MachinePerformanceResponsePlanningService:
    def build_query_plan(self, intent: dict) -> dict:
        intent_type = intent.get("intent_type") or "single_kpi"
        diagnostics = (
            intent.get("metric") == "availability" and intent_type == "single_kpi"
            if intent.get("_adaptive_responses_enabled") is False
            else intent_type in {"downtime_drivers", "root_cause_analysis"}
        )
        primary_query_intents = {
            "single_kpi", "entity_comparison", "period_comparison",
            "trend_analysis", "ranking", "root_cause_analysis",
            "performance_overview", "equipment_detail",
        }
        return {
            "execute_primary_metric": (
                intent_type in {"performance_overview", "equipment_detail"}
                or (bool(intent.get("primary_metric") or intent.get("metric")) and intent_type in primary_query_intents)
            ),
            "execute_downtime_diagnostics": diagnostics,
            "group_by": list(intent.get("group_by") or []),
            "required_data": _query_requirements(intent_type),
        }

    def build_response_envelope(self, *, intent: dict, result: dict, answer_text: str) -> dict:
        plan = MachinePerformanceResponseTemplateResolver().resolve(intent, result)
        actions = [
            {"code": code, "label": ACTION_LABELS.get(code, code.replace("_", " ").title())}
            for code in ACTIONS.get(plan.code, ACTIONS["generic_analytical"])
        ][:4]
        return {
            "answer_text": answer_text,
            "intent": {
                "type": intent.get("intent_type"),
                "scope_type": intent.get("scope_type"),
                "primary_metric": intent.get("primary_metric") or intent.get("metric"),
            },
            "presentation": {
                "template_code": plan.code,
                "template_version": plan.version,
                "components": plan.components,
                "required_data": plan.required_fields,
                "fallback_template": plan.fallback,
            },
            "context": dict(intent.get("filters") or {}),
            "actions": actions,
            "warnings": plan.warnings,
        }


def adaptive_performance_responses_enabled(user=None) -> bool:
    mode = str(getattr(settings, "ENABLE_ADAPTIVE_PERFORMANCE_RESPONSES", "Production") or "Production").strip().casefold()
    if mode == "disabled":
        return False
    if mode in {"admin only", "pilot"}:
        return bool(user and (getattr(user, "is_staff", False) or getattr(user, "is_superuser", False)))
    return True

def _query_requirements(intent_type: str) -> list[str]:
    return {
        "single_kpi": ["primary_metric"],
        "performance_overview": ["metric_grid"],
        "equipment_detail": ["equipment_identity", "equipment_metrics"],
        "downtime_drivers": ["downtime_diagnostics"],
        "entity_comparison": ["grouped_metric"],
        "period_comparison": ["period_grouped_metric"],
        "trend_analysis": ["time_series"],
        "ranking": ["ranked_metric"],
        "affected_equipment": ["equipment_list"],
        "downtime_events": ["event_list"],
        "root_cause_analysis": ["downtime_diagnostics", "evidence"],
    }.get(intent_type, ["result_rows"])


def _available_data_fields(intent: dict, result: dict) -> set[str]:
    rows = result.get("rows") if isinstance(result.get("rows"), list) else []
    diagnostics = result.get("availability_diagnostics") or result.get("downtime_diagnostics") or {}
    available = set()
    if rows:
        available.add("rows")
        available.add("metric_value")
    if len(rows) >= 2:
        available.add("multiple_rows")
    if diagnostics.get("drivers"):
        available.add("downtime_drivers")
    if (intent.get("filters") or {}).get("serial_number"):
        available.add("equipment_identity")
    return available
