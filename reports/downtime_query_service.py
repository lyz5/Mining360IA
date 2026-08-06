from __future__ import annotations

import hashlib
import json
import time

from django.core.cache import cache

from .ai_config_service import get_dax_template, get_filter_mapping
from .dax_generator_service import _build_filter_clause, _dax_column, _filter_clauses
from .models import (
    DowntimeExplorerInteraction,
    DowntimeExplorerSession,
    RootCauseDimension,
)
from .power_automate import execute_dax_via_flow
from .powerbi import resolve_dataset_roles
from .powerbi_interaction_service import _period_navigation_range


CACHE_SECONDS = 600
TABLE = "DowntimeData_MiningProd"
MEASURE = "[DonwtimeHours]"
EVENT_COUNT_MEASURE = "[Nb DT]"


def _extract_rows(value) -> list[dict]:
    if isinstance(value, list):
        for item in value:
            rows = _extract_rows(item)
            if rows:
                return rows
        return []
    if not isinstance(value, dict):
        return []
    if isinstance(value.get("firstTableRows"), list):
        return [row for row in value["firstTableRows"] if isinstance(row, dict)]
    try:
        rows = value["results"][0]["tables"][0]["rows"]
        if isinstance(rows, list):
            return rows
    except (KeyError, IndexError, TypeError):
        pass
    for item in value.values():
        rows = _extract_rows(item)
        if rows:
            return rows
    return []


def _configured_dimension(code: str) -> RootCauseDimension:
    dimension = RootCauseDimension.objects.filter(
        section__code="performance",
        code=code,
        is_active=True,
        validation_status="Validated",
    ).first()
    if not dimension:
        raise ValueError(
            "The selected root cause dimension is not mapped to the semantic model."
        )
    return dimension


def available_dimensions() -> list[dict]:
    return [
        {
            "code": item.code,
            "display_name": item.display_name,
            "parent": item.parent_dimension.code if item.parent_dimension else None,
            "hierarchy_level": item.hierarchy_level,
            "is_clickable": item.is_clickable,
        }
        for item in RootCauseDimension.objects.select_related(
            "parent_dimension"
        ).filter(
            section__code="performance",
            is_active=True,
            validation_status="Validated",
            available_for_breakdown=True,
        )
    ]


def _base_clauses(session: DowntimeExplorerSession) -> list[str]:
    mappings = {
        item["filter_code"]: item
        for item in get_filter_mapping("performance")
        if item.get("is_active")
    }
    return _filter_clauses(
        session.context_json.get("filters") or {},
        mappings,
    )


def _clauses(session: DowntimeExplorerSession) -> list[str]:
    clauses = _base_clauses(session)
    selections = session.context_json.get("selections") or {}
    for code, value in selections.items():
        dimension = _configured_dimension(code)
        clauses.append(
            _build_filter_clause(
                {
                    "powerbi_table_name": dimension.semantic_table,
                    "powerbi_column_name": dimension.semantic_column,
                    "data_type": "Text",
                },
                value,
            )
        )
    return clauses


def _event_clauses(session: DowntimeExplorerSession) -> list[str]:
    """Apply canonical filters plus direct fact-table filters for event rows."""
    clauses = _clauses(session)
    filters = session.context_json.get("filters") or {}
    direct_columns = {
        "minesite": "Site",
        "model": "Model",
        "serial_number": "SN",
    }
    for code, column in direct_columns.items():
        value = filters.get(code)
        if value not in (None, "", []):
            clauses.append(
                _build_filter_clause(
                    {
                        "powerbi_table_name": TABLE,
                        "powerbi_column_name": column,
                        "data_type": "Text",
                    },
                    value,
                )
            )
    period_range = _period_navigation_range(filters.get("period"))
    if period_range:
        start, end = period_range
        period_column = _dax_column(TABLE, "MonthYear")
        clauses.append(
            f"FILTER(ALL({period_column}), "
            f"{period_column} >= DATE({start.year}, {start.month}, {start.day}) && "
            f"{period_column} <= DATE({end.year}, {end.month}, {end.day}))"
        )
    return clauses


def _calculate(expression: str, clauses: list[str]) -> str:
    if not clauses:
        return expression
    return f"CALCULATE({expression}, {', '.join(clauses)})"


def build_summary_dax(session: DowntimeExplorerSession) -> str:
    if not get_dax_template("performance", "DOWNTIME_DRIVER_SUMMARY"):
        raise ValueError("DOWNTIME_DRIVER_SUMMARY is not configured.")
    clauses = _clauses(session)
    total_hours = _calculate(MEASURE, _base_clauses(session))
    hours = _calculate(MEASURE, clauses)
    events = _calculate(EVENT_COUNT_MEASURE, clauses)
    equipment = _calculate(
        f"DISTINCTCOUNT({_dax_column(TABLE, 'SN')})",
        clauses,
    )
    median = _calculate(f"MEDIAN({_dax_column(TABLE, 'DowntimeHours')})", clauses)
    longest = _calculate(f"MAX({_dax_column(TABLE, 'DowntimeHours')})", clauses)
    return (
        "EVALUATE\nROW(\n"
        f'    "Downtime Hours", {hours},\n'
        f'    "Total Context Downtime Hours", {total_hours},\n'
        f'    "Contribution", DIVIDE({hours}, {total_hours}),\n'
        f'    "Event Count", {events},\n'
        f'    "Affected Equipment", {equipment},\n'
        f'    "Average Duration", DIVIDE({hours}, {events}),\n'
        f'    "Median Duration", {median},\n'
        f'    "Longest Event", {longest}\n'
        ")"
    )


def build_breakdown_dax(
    session: DowntimeExplorerSession,
    dimension_code: str,
    limit: int = 30,
) -> str:
    if not get_dax_template("performance", "DOWNTIME_BREAKDOWN_BY_DIMENSION"):
        raise ValueError("DOWNTIME_BREAKDOWN_BY_DIMENSION is not configured.")
    dimension = _configured_dimension(dimension_code)
    if not dimension.available_for_breakdown:
        raise ValueError("This dimension is not available for breakdown.")
    column = _dax_column(dimension.semantic_table, dimension.semantic_column)
    args = [
        column,
        *_clauses(session),
        f'"Downtime Hours", {MEASURE}',
        f'"Event Count", {EVENT_COUNT_MEASURE}',
        f'"Affected Equipment", DISTINCTCOUNT({_dax_column(TABLE, "SN")})',
        f'"Average Duration", DIVIDE({MEASURE}, {EVENT_COUNT_MEASURE})',
        f'"Longest Event", MAX({_dax_column(TABLE, "DowntimeHours")})',
    ]
    return (
        "EVALUATE\n"
        f"TOPN({max(1, min(int(limit), 100))},\n"
        "    SUMMARIZECOLUMNS(\n"
        f"        {',\n        '.join(args)}\n"
        "    ),\n"
        "    [Downtime Hours], DESC\n"
        ")\n"
        "ORDER BY [Downtime Hours] DESC"
    )


def build_equipment_dax(session: DowntimeExplorerSession, limit: int = 50) -> str:
    if not get_dax_template("performance", "DOWNTIME_AFFECTED_EQUIPMENT"):
        raise ValueError("DOWNTIME_AFFECTED_EQUIPMENT is not configured.")
    columns = [
        _dax_column(TABLE, "SN"),
        _dax_column(TABLE, "Equip"),
        _dax_column(TABLE, "Model"),
        _dax_column(TABLE, "Site"),
    ]
    args = [
        *columns,
        *_clauses(session),
        f'"Downtime Hours", {MEASURE}',
        f'"Event Count", {EVENT_COUNT_MEASURE}',
        f'"Average Duration", DIVIDE({MEASURE}, {EVENT_COUNT_MEASURE})',
        f'"Longest Event", MAX({_dax_column(TABLE, "DowntimeHours")})',
        f'"Latest Event Date", MAX({_dax_column(TABLE, "EndHours")})',
    ]
    return (
        "EVALUATE\n"
        f"TOPN({max(1, min(int(limit), 200))},\n"
        "    SUMMARIZECOLUMNS(\n"
        f"        {',\n        '.join(args)}\n"
        "    ),\n"
        "    [Downtime Hours], DESC\n"
        ")\n"
        "ORDER BY [Downtime Hours] DESC"
    )


def build_events_dax(session: DowntimeExplorerSession, limit: int = 200) -> str:
    if not get_dax_template("performance", "DOWNTIME_EVENT_LIST"):
        raise ValueError("DOWNTIME_EVENT_LIST is not configured.")
    fields = [
        ("MineSite", "Site"),
        ("Serial Number", "SN"),
        ("Equipment", "Equip"),
        ("Equipment ID", "Equipment_ID"),
        ("Model", "Model"),
        ("Start Date", "StartHours"),
        ("End Date", "EndHours"),
        ("Duration", "DowntimeHours"),
        ("Downtime Driver", "DescriptionCat"),
        ("Work Type", "WorkType"),
        ("Labour Type", "LabourType"),
        ("Comment", "Comments"),
        ("Period", "MonthYear"),
    ]
    selected = ",\n            ".join(
        f'"{label}", {_dax_column(TABLE, column)}'
        for label, column in fields
    )
    return (
        "EVALUATE\n"
        "VAR FilteredEvents =\n"
        "    CALCULATETABLE(\n"
        "        SELECTCOLUMNS(\n"
        f"            '{TABLE}',\n"
        f"            {selected}\n"
        "        ),\n"
        f"        {',\n        '.join(_event_clauses(session))}\n"
        "    )\n"
        "RETURN\n"
        f"TOPN({max(1, min(int(limit), 500))}, FilteredEvents, "
        "[Start Date], DESC, [Duration], DESC)\n"
        "ORDER BY [Start Date] DESC, [Duration] DESC"
    )


def _cache_key(session, level: str, dax: str) -> str:
    raw = f"{session.user_id}|{session.semantic_model_id}|{session.context_hash}|{level}|{dax}"
    return "dt-explorer:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def execute_explorer_dax(
    session: DowntimeExplorerSession,
    *,
    level: str,
    dax: str,
) -> dict:
    key = _cache_key(session, level, dax)
    cached = cache.get(key)
    if cached is not None:
        return {"rows": cached, "cached": True, "execution_time_ms": 0}
    started = time.monotonic()
    site = (session.context_json.get("filters") or {}).get("minesite")
    site_value = site[0] if isinstance(site, list) and site else site
    roles = resolve_dataset_roles(
        session.semantic_model_name,
        [str(site_value)],
    ) if site_value else []
    payload = {
        "datasetId": session.semantic_model_id,
        "datasetName": session.semantic_model_name,
        "query": dax,
        "question": f"Downtime Root Cause Explorer: {level}",
        "metric": "downtime_hours",
        "measure": MEASURE,
        "filters": session.context_json.get("filters") or {},
        "section": "performance",
        "rlsRole": roles[0] if roles else "",
        "roles": roles,
    }
    response = execute_dax_via_flow(payload)
    rows = _extract_rows(response)
    elapsed = int((time.monotonic() - started) * 1000)
    cache.set(key, rows, CACHE_SECONDS)
    DowntimeExplorerInteraction.objects.create(
        session=session,
        interaction_type=f"Load {level}",
        previous_context=session.context_json,
        new_context=session.context_json,
        query_execution_id=hashlib.sha256(dax.encode("utf-8")).hexdigest()[:32],
        execution_time_ms=elapsed,
        result_count=len(rows),
    )
    return {"rows": rows, "cached": False, "execution_time_ms": elapsed}
