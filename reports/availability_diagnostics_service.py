from __future__ import annotations

from .ai_config_service import get_filter_mapping, get_metric_mapping
from .dax_generator_service import _dax_column, _filter_clauses


class AvailabilityDiagnosticsConfigurationError(RuntimeError):
    pass


def _active_by_code(items: list[dict], code_field: str, code: str) -> dict | None:
    return next(
        (
            item for item in items
            if item.get(code_field) == code and item.get("is_active")
        ),
        None,
    )


def build_availability_diagnostics_dax(
    intent: dict,
    *,
    top_n: int = 10,
    work_type: str = "",
) -> dict:
    section_code = str(intent.get("section") or "")
    metrics = get_metric_mapping(section_code)
    filters_config = get_filter_mapping(section_code)
    hours_metric = _active_by_code(metrics, "metric_code", "downtime_hours")
    driver_mapping = _active_by_code(
        filters_config,
        "filter_code",
        "downtime_driver",
    )
    if not hours_metric:
        raise AvailabilityDiagnosticsConfigurationError(
            "The downtime_hours metric is not configured."
        )
    if not driver_mapping:
        raise AvailabilityDiagnosticsConfigurationError(
            "The downtime_driver filter is not configured."
        )

    try:
        limit = max(1, min(int(top_n), 25))
    except (TypeError, ValueError):
        limit = 10

    reusable_filters = {
        code: value
        for code, value in (intent.get("filters") or {}).items()
        if code != "downtime_driver"
    }
    filters_lookup = {
        item["filter_code"]: item
        for item in filters_config
        if item.get("is_active")
    }
    clauses = _filter_clauses(reusable_filters, filters_lookup)
    normalized_work_type = str(work_type or "").strip().title()
    if normalized_work_type:
        if normalized_work_type not in {"Planned", "Unplanned"}:
            raise AvailabilityDiagnosticsConfigurationError(
                "Work Type must be Planned or Unplanned."
            )
        clauses.append(
            "TREATAS({\""
            + normalized_work_type.replace('"', '""')
            + "\"}, 'DowntimeData_MiningProd'[WorkType])"
        )
    driver_column = _dax_column(
        driver_mapping["powerbi_table_name"],
        driver_mapping["powerbi_column_name"],
    )
    measure = hours_metric["powerbi_measure_name"]
    summarize_args = [
        driver_column,
        *clauses,
        f'"Downtime Hours", {measure}',
        '"Event Count", [Nb DT]',
        (
            '"Average Event Duration", '
            f'DIVIDE({measure}, [Nb DT])'
        ),
        (
            '"Affected Equipment", '
            "DISTINCTCOUNT('DowntimeData_MiningProd'[SN])"
        ),
        (
            '"Total Downtime Hours", '
            f"CALCULATE({measure}, REMOVEFILTERS({driver_column}))"
        ),
    ]
    dax = (
        "EVALUATE\n"
        "VAR DowntimeDrivers =\n"
        "    SUMMARIZECOLUMNS(\n"
        f"        {',\n        '.join(summarize_args)}\n"
        "    )\n"
        "VAR ValidDrivers =\n"
        "    FILTER(\n"
        "        DowntimeDrivers,\n"
        f"        NOT ISBLANK({driver_column}) && [Downtime Hours] > 0\n"
        "    )\n"
        "RETURN\n"
        f"TOPN({limit}, ValidDrivers, [Downtime Hours], DESC, "
        f"{driver_column}, ASC)\n"
        "ORDER BY [Downtime Hours] DESC"
    )
    return {
        "section": section_code,
        "metric": "downtime_hours",
        "measure": measure,
        "filters": reusable_filters,
        "driver_table": driver_mapping["powerbi_table_name"],
        "driver_column": driver_mapping["powerbi_column_name"],
        "work_type": normalized_work_type,
        "dax": dax,
    }


def _row_value(row: dict, label: str):
    expected = label.casefold()
    for key, value in row.items():
        if expected in str(key).casefold():
            return value
    return None


def parse_availability_diagnostics_rows(rows: list[dict]) -> dict:
    drivers = []
    total_hours = None
    for row in rows:
        driver = _row_value(row, "DescriptionCat")
        hours = _row_value(row, "Downtime Hours")
        total = _row_value(row, "Total Downtime Hours")
        event_count = _row_value(row, "Event Count")
        average_duration = _row_value(row, "Average Event Duration")
        affected_equipment = _row_value(row, "Affected Equipment")
        try:
            hours_value = float(hours)
        except (TypeError, ValueError):
            continue
        if not driver or hours_value <= 0:
            continue
        if total_hours is None:
            try:
                total_hours = float(total)
            except (TypeError, ValueError):
                total_hours = None
        drivers.append({
            "driver": str(driver),
            "hours": round(hours_value, 2),
            "event_count": int(float(event_count or 0)),
            "average_event_duration": round(float(average_duration or 0), 2),
            "affected_equipment": int(float(affected_equipment or 0)),
        })

    drivers.sort(key=lambda item: (-item["hours"], item["driver"].casefold()))
    if total_hours is None:
        total_hours = sum(item["hours"] for item in drivers)
    total_hours = max(float(total_hours or 0), 0)
    cumulative = 0.0
    for item in drivers:
        share = (item["hours"] / total_hours * 100) if total_hours else 0
        cumulative += share
        item["share_percentage"] = round(share, 2)
        item["cumulative_percentage"] = round(min(cumulative, 100), 2)
    return {
        "total_downtime_hours": round(total_hours, 2),
        "drivers": drivers,
    }


def enrich_availability_answer(answer: str, diagnostics: dict) -> str:
    total = diagnostics.get("total_downtime_hours")
    drivers = diagnostics.get("drivers") or []
    if total is None:
        return answer
    lines = [
        answer,
        "",
        f"Total downtime: {float(total):,.2f} h.",
    ]
    if drivers:
        lines.append("Top downtime drivers:")
        for item in drivers[:5]:
            lines.append(
                f"- {item['driver']} : {item['hours']:,.2f} h "
                f"({item['share_percentage']:.1f} %, "
                f"cumul {item['cumulative_percentage']:.1f} %)"
            )
    else:
        lines.append("No downtime driver was returned for this context.")
    return "\n".join(lines)
