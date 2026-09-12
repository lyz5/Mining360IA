from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import OperationalError, ProgrammingError
from django.conf import settings

from .models import AIIntentResponseTemplateMapping, AIResponseTemplate


DEFAULT_TEMPLATES = {
    "single_kpi": ["primary_metric", "context", "contextual_actions"],
    "performance_overview": ["metric_grid", "key_takeaway", "contextual_actions"],
    "fleet_performance_overview": ["context", "data_coverage", "metric_grid", "key_takeaway", "contextual_actions"],
    "reliability_overview": ["context", "metric_grid", "trend_chart", "key_takeaway", "contextual_actions"],
    "multi_kpi_summary": ["context", "metric_grid", "key_takeaway", "contextual_actions"],
    "planned_unplanned_analysis": ["context", "metric_grid", "comparison_summary", "key_takeaway", "contextual_actions"],
    "fleet_performance_comparison": ["context", "comparison_table", "key_takeaway", "contextual_actions"],
    "fleet_performance_period_comparison": ["context", "comparison_table", "key_takeaway", "contextual_actions"],
    "fleet_performance_trend": ["context", "trend_chart", "result_table", "key_takeaway", "contextual_actions"],
    "fleet_performance_ranking": ["context", "ranking_table", "key_takeaway", "contextual_actions"],
    "equipment_performance_detail": ["equipment_identity", "metric_grid", "contextual_actions"],
    "component_analysis": ["context", "result_table", "key_takeaway", "contextual_actions"],
    "pm_analysis": ["context", "result_table", "key_takeaway", "contextual_actions"],
    "smu_tracking": ["context", "result_table", "contextual_actions"],
    "fleet_performance_benchmark": ["context", "comparison_table", "key_takeaway", "contextual_actions"],
    "equipment_detail": ["equipment_identity", "metric_grid", "result_table", "contextual_actions"],
    "fleet_inventory": ["context", "equipment_table", "contextual_actions"],
    "get_site_fleet": ["fleet_summary", "fleet_model_summary", "fleet_equipment_table", "contextual_actions"],
    "get_site_fleet_by_model": ["fleet_summary", "fleet_model_summary", "fleet_equipment_table", "contextual_actions"],
    "get_site_model_fleet": ["fleet_summary", "fleet_equipment_table", "contextual_actions"],
    "get_fleet_count": ["fleet_summary", "fleet_model_summary", "contextual_actions"],
    "lookup_equipment_by_serial": ["equipment_master_detail", "contextual_actions"],
    "lookup_equipment_by_code": ["equipment_master_detail", "contextual_actions"],
    "export_current_fleet": ["fleet_export_confirmation", "contextual_actions"],
    "performance_export_confirmation": ["context", "metric_grid", "contextual_actions"],
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
    "fleet_performance_overview": ["compare", "show_trend", "show_downtime_drivers", "open_powerbi"],
    "reliability_overview": ["show_trend", "compare", "view_affected_equipment", "open_powerbi"],
    "multi_kpi_summary": ["show_trend", "compare", "download_excel", "open_powerbi"],
    "planned_unplanned_analysis": ["compare_periods", "view_affected_equipment", "download_excel", "open_powerbi"],
    "fleet_performance_comparison": ["change_metric", "show_trend", "download_excel", "open_powerbi"],
    "fleet_performance_period_comparison": ["show_trend", "download_excel", "open_powerbi"],
    "fleet_performance_trend": ["compare_periods", "download_excel", "open_powerbi"],
    "fleet_performance_ranking": ["open_equipment", "change_ranking", "download_excel", "open_powerbi"],
    "equipment_performance_detail": ["show_downtime_drivers", "show_events", "download_excel", "open_powerbi"],
    "component_analysis": ["view_affected_equipment", "show_events", "download_excel", "open_powerbi"],
    "pm_analysis": ["view_affected_equipment", "show_events", "download_excel", "open_powerbi"],
    "smu_tracking": ["open_equipment", "download_excel", "open_powerbi"],
    "fleet_performance_benchmark": ["change_metric", "view_entity", "download_excel", "open_powerbi"],
    "downtime_drivers": ["explore_driver", "view_affected_equipment", "show_events", "show_pareto"],
    "entity_comparison": ["change_metric", "view_entity", "compare_drivers", "open_powerbi"],
    "period_comparison": ["show_trend", "compare_drivers", "open_powerbi"],
    "trend_analysis": ["compare_periods", "show_anomalies", "show_downtime_drivers"],
    "ranking": ["open_equipment", "change_ranking", "open_powerbi"],
    "equipment_detail": ["show_events", "analyze_comments", "repeated_failures", "open_powerbi"],
    "fleet_inventory": ["open_equipment", "open_powerbi"],
    "get_site_fleet": ["download_excel", "filter_model", "search_equipment", "open_powerbi"],
    "get_site_fleet_by_model": ["download_excel", "filter_model", "search_equipment", "open_powerbi"],
    "get_site_model_fleet": ["download_excel", "view_all_models", "open_equipment", "open_powerbi"],
    "get_fleet_count": ["view_site_fleet", "filter_model", "download_excel"],
    "lookup_equipment_by_serial": ["view_site_fleet", "view_same_model", "open_equipment", "open_powerbi"],
    "lookup_equipment_by_code": ["view_site_fleet", "view_same_model", "open_equipment", "open_powerbi"],
    "export_current_fleet": ["download_excel", "view_site_fleet"],
    "performance_export_confirmation": ["download_excel"],
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
    "download_excel": "Download Excel", "filter_model": "Filter by Model",
    "search_equipment": "Search Equipment", "view_all_models": "View All Models",
    "view_site_fleet": "View Site Fleet", "view_same_model": "View Same Model",
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
        fleet_template_codes = {
            "entity_comparison": "fleet_performance_comparison",
            "period_comparison": "fleet_performance_period_comparison",
            "trend_analysis": "fleet_performance_trend",
            "ranking": "fleet_performance_ranking",
            "equipment_performance": "equipment_performance_detail",
            "serial_performance": "equipment_performance_detail",
            "benchmark_analysis": "fleet_performance_benchmark",
            "export_current_result": "performance_export_confirmation",
        }
        try:
            if intent.get("capability") == "fleet_performance" and intent_type in fleet_template_codes:
                template = AIResponseTemplate.objects.filter(
                    code=fleet_template_codes[intent_type], active=True,
                    validation_status="Validated",
                ).first()
            if template is None:
                mappings = AIIntentResponseTemplateMapping.objects.select_related("response_template").filter(
                    domain="machine_performance",
                    intent_type=intent_type,
                    active=True,
                    validation_status="Validated",
                    response_template__active=True,
                    response_template__validation_status="Validated",
                )
                if intent.get("capability") != "fleet_performance":
                    mappings = mappings.exclude(response_template__code__startswith="fleet_performance_")
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

        fallback_codes = {
            "entity_comparison": "fleet_performance_comparison" if intent.get("capability") == "fleet_performance" else "entity_comparison",
            "period_comparison": "fleet_performance_period_comparison" if intent.get("capability") == "fleet_performance" else "period_comparison",
            "trend_analysis": "fleet_performance_trend" if intent.get("capability") == "fleet_performance" else "trend_analysis",
            "ranking": "fleet_performance_ranking" if intent.get("capability") == "fleet_performance" else "ranking",
            "equipment_performance": "equipment_performance_detail",
            "serial_performance": "equipment_performance_detail",
            "benchmark_analysis": "fleet_performance_benchmark",
            "export_current_result": "performance_export_confirmation",
        }
        default_code = fallback_codes.get(intent_type, intent_type)
        code = template.code if template else (default_code if default_code in DEFAULT_TEMPLATES else "generic_analytical")
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
            "fleet_inventory", "get_site_fleet", "get_site_fleet_by_model",
            "get_site_model_fleet", "get_fleet_count", "lookup_equipment_by_serial",
            "lookup_equipment_by_code",
            "export_current_fleet",
            "fleet_performance_overview", "reliability_overview", "multi_kpi_summary",
            "site_performance", "model_performance", "equipment_performance", "serial_performance",
            "planned_unplanned_analysis", "most_impacted_equipment",
            "down_hours_by_compartment", "down_hours_by_equipment", "component_analysis",
            "pm_analysis", "smu_tracking", "benchmark_analysis",
        }
        return {
            "execute_primary_metric": (
                intent_type in {
                    "performance_overview", "equipment_detail", "fleet_performance_overview",
                    "reliability_overview", "multi_kpi_summary", "site_performance",
                    "model_performance", "equipment_performance", "serial_performance",
                    "planned_unplanned_analysis", "benchmark_analysis", "smu_tracking",
                    "pm_analysis", "component_analysis", "down_hours_by_compartment",
                    "down_hours_by_equipment", "most_impacted_equipment",
                }
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


def _rollout_enabled(setting_name: str, user=None, default: str = "Admin Only") -> bool:
    mode = str(getattr(settings, setting_name, default) or default).strip().casefold()
    if mode == "disabled":
        return False
    if mode in {"admin only", "pilot"}:
        return bool(user and (getattr(user, "is_staff", False) or getattr(user, "is_superuser", False)))
    return True


def complete_fleet_performance_enabled(user=None) -> bool:
    return _rollout_enabled("ENABLE_COMPLETE_FLEET_PERFORMANCE_CHAT", user)


def fleet_performance_operation_enabled(intent_type: str, user=None) -> bool:
    setting_name = {
        "entity_comparison": "ENABLE_FLEET_PERFORMANCE_COMPARISON",
        "period_comparison": "ENABLE_FLEET_PERFORMANCE_COMPARISON",
        "benchmark_analysis": "ENABLE_FLEET_PERFORMANCE_COMPARISON",
        "trend_analysis": "ENABLE_FLEET_PERFORMANCE_TRENDS",
        "ranking": "ENABLE_FLEET_PERFORMANCE_RANKING",
        "planned_unplanned_analysis": "ENABLE_PLANNED_UNPLANNED_ANALYSIS",
        "export_current_result": "ENABLE_FLEET_PERFORMANCE_EXPORT",
        "root_cause_analysis": "ENABLE_FLEET_PERFORMANCE_DIAGNOSTICS",
        "downtime_drivers": "ENABLE_FLEET_PERFORMANCE_DIAGNOSTICS",
        "component_analysis": "ENABLE_FLEET_PERFORMANCE_DIAGNOSTICS",
        "pm_analysis": "ENABLE_FLEET_PERFORMANCE_DIAGNOSTICS",
    }.get(str(intent_type or ""))
    return True if not setting_name else _rollout_enabled(setting_name, user)

def _query_requirements(intent_type: str) -> list[str]:
    return {
        "single_kpi": ["primary_metric"],
        "performance_overview": ["metric_grid"],
        "fleet_performance_overview": ["metric_grid", "data_coverage"],
        "reliability_overview": ["metric_grid"],
        "multi_kpi_summary": ["metric_grid"],
        "planned_unplanned_analysis": ["metric_grid"],
        "benchmark_analysis": ["grouped_metric"],
        "equipment_performance": ["equipment_identity", "equipment_metrics"],
        "serial_performance": ["equipment_identity", "equipment_metrics"],
        "equipment_detail": ["equipment_identity", "equipment_metrics"],
        "fleet_inventory": ["equipment_list"],
        "get_site_fleet": ["fleet_equipment_table", "fleet_model_summary"],
        "get_site_fleet_by_model": ["fleet_equipment_table", "fleet_model_summary"],
        "get_site_model_fleet": ["fleet_equipment_table"],
        "get_fleet_count": ["fleet_model_summary"],
        "lookup_equipment_by_serial": ["equipment_identity"],
        "lookup_equipment_by_code": ["equipment_identity"],
        "export_current_fleet": ["fleet_equipment_table"],
        "export_current_result": [],
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
    if result.get("fleet_inventory"):
        available.update({"fleet_equipment_table", "fleet_model_summary"})
    if result.get("equipment_identity"):
        available.add("equipment_identity")
    return available
