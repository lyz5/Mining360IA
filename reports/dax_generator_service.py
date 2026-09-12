from __future__ import annotations

from datetime import date
import re

from .ai_config_service import get_dax_template, get_metric_mapping, get_filter_mapping, get_section_by_code
from .fleet_performance_intelligence_service import metrics_for_intent
from .temporal_expression_resolution_service import normalize_period_value


class IntentValidationError(RuntimeError):
    pass


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _quote_dax_text(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def validate_intent(intent: dict) -> tuple[bool, list[str]]:
    errors: list[str] = []
    section_code = str(intent.get("section") or "").strip()
    section = get_section_by_code(section_code)
    if not section:
        errors.append("Section does not exist or is inactive.")
        return False, errors

    metric_code = str(intent.get("metric") or "").strip()
    if not metric_code:
        errors.append("Metric is missing.")
    else:
        metric = next((item for item in get_metric_mapping(section.code) if item["metric_code"] == metric_code and item["is_active"]), None)
        if not metric:
            errors.append(f"Metric '{metric_code}' is not configured for section '{section.code}'.")

    filters = intent.get("filters") or {}
    if not isinstance(filters, dict):
        errors.append("Filters must be an object.")
        return False, errors

    configured_filters = {item["filter_code"]: item for item in get_filter_mapping(section.code) if item["is_active"]}
    for key, value in filters.items():
        if key not in configured_filters:
            errors.append(f"Filter '{key}' is not configured for section '{section.code}'.")
        elif value in (None, "") and configured_filters[key]["is_required"]:
            errors.append(f"Filter '{key}' is required.")
    for key, mapping in configured_filters.items():
        if mapping["is_required"] and key not in filters:
            errors.append(f"Required filter '{key}' is missing.")

    return not errors, errors


def _dax_literal(value, data_type: str | None = None) -> str:
    if value is None:
        return "BLANK()"
    if isinstance(value, bool):
        return "TRUE()" if value else "FALSE()"
    text = str(value).strip()
    dtype = _normalize(data_type or "")
    if dtype in {"integer", "int", "decimal", "number"}:
        if re.fullmatch(r"-?\d+(?:\.\d+)?", text):
            return text
        return _quote_dax_text(text)
    if dtype in {"date", "datetime"}:
        if re.fullmatch(r"20\d{2}-\d{2}", text):
            year, month = text.split("-")
            return f'DATE({int(year)}, {int(month)}, 1)'
        if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", text):
            year, month, day = text.split("-")
            return f'DATE({int(year)}, {int(month)}, {int(day)})'
    return _quote_dax_text(text)


def _build_filter_clause(mapping: dict, value) -> str:
    values = value if isinstance(value, list) else [value]
    literals = ", ".join(_dax_literal(item, mapping.get("data_type")) for item in values)
    table = mapping["powerbi_table_name"]
    column = mapping["powerbi_column_name"]
    return f"TREATAS({{{literals}}}, '{table}'[{column}])"


def _dax_column(table: str, column: str) -> str:
    escaped_table = str(table).replace("'", "''")
    escaped_column = str(column).replace("]", "]]")
    return f"'{escaped_table}'[{escaped_column}]"


def _build_period_clause(value, mapping: dict) -> str | None:
    if value in (None, ""):
        return None
    value = normalize_period_value(value)
    text = str(value).strip().lower()
    date_column = _dax_column(mapping["powerbi_table_name"], "Date")
    # Fleet Performance visuals evaluate relative periods against the report
    # calendar through today. Capping the governed Date dimension prevents a
    # future calendar horizon from entering YTD/MTD while preserving report parity.
    latest_date = (
        f"MIN(TODAY(), CALCULATE(MAX({date_column}), REMOVEFILTERS('Date')))"
    )
    if text == "year to date":
        return (
            f"DATESBETWEEN({date_column}, "
            f"DATE(YEAR({latest_date}), 1, 1), {latest_date})"
        )
    if text == "month to date":
        return (
            f"DATESBETWEEN({date_column}, "
            f"DATE(YEAR({latest_date}), MONTH({latest_date}), 1), {latest_date})"
        )
    rolling_match = re.fullmatch(r"last (\d{1,3}) months?", text)
    if rolling_match:
        months = int(rolling_match.group(1))
        if 1 <= months <= 120:
            return f"DATESINPERIOD({date_column}, {latest_date}, -{months}, MONTH)"
    if text in {"current month", "ce mois", "mois courant"}:
        return f"DATESBETWEEN({date_column}, DATE(YEAR({latest_date}), MONTH({latest_date}), 1), {latest_date})"
    if text in {"previous month", "last month", "mois précédent", "mois precedent"}:
        return (
            f"DATESBETWEEN({date_column}, "
            f"EOMONTH({latest_date}, -2) + 1, "
            f"EOMONTH({latest_date}, -1))"
        )
    match = re.fullmatch(r"(20\d{2})", text)
    if match:
        year = int(match.group(1))
        return f"DATESBETWEEN({date_column}, DATE({year}, 1, 1), DATE({year}, 12, 31))"
    match = re.fullmatch(r"(20\d{2})-(\d{2})/(20\d{2})-(\d{2})", text)
    if match:
        start_year, start_month, end_year, end_month = map(int, match.groups())
        if (
            1 <= start_month <= 12
            and 1 <= end_month <= 12
            and (end_year, end_month) >= (start_year, start_month)
        ):
            return (
                f"DATESBETWEEN({date_column}, "
                f"DATE({start_year}, {start_month}, 1), "
                f"EOMONTH(DATE({end_year}, {end_month}, 1), 0))"
            )
    match = re.fullmatch(r"(20\d{2})-(\d{2})", text)
    if match:
        year = int(match.group(1))
        month = int(match.group(2))
        return f"DATESBETWEEN({date_column}, DATE({year}, {month}, 1), EOMONTH(DATE({year}, {month}, 1), 0))"
    match = re.fullmatch(r"(20\d{2})-(\d{2})-(\d{2})", text)
    if match:
        year = int(match.group(1))
        month = int(match.group(2))
        day = int(match.group(3))
        return f"DATESBETWEEN({date_column}, DATE({year}, {month}, {day}), DATE({year}, {month}, {day}))"
    return _build_filter_clause(mapping, value)


def _filter_clauses(filters: dict, filters_config: dict) -> list[str]:
    clauses = []
    for filter_code, value in filters.items():
        if value in (None, ""):
            continue
        mapping = filters_config.get(filter_code)
        if not mapping:
            continue
        if filter_code == "period":
            clause = _build_period_clause(value, mapping)
        else:
            clause = _build_filter_clause(mapping, value)
        if clause:
            clauses.append(clause)
    return clauses


def _is_last_12_months(value) -> bool:
    text = str(value or "").strip().lower()
    return text in {"last 12 months", "douze derniers mois", "12 derniers mois"}


def _report_aligned_availability_ytd_expression(metric: dict, period_mapping: dict) -> str:
    """Aggregate the non-additive monthly availability at the report's day grain."""
    date_column = _dax_column(period_mapping["powerbi_table_name"], "Date")
    measure = metric["powerbi_measure_name"]
    return (
        "VAR __Months =\n"
        "    DISTINCT(\n"
        "        SELECTCOLUMNS(\n"
        f"            VALUES({date_column}),\n"
        f"            \"__MonthEnd\", EOMONTH({date_column}, 0)\n"
        "        )\n"
        "    )\n"
        "VAR __WeightedAvailability =\n"
        "    SUMX(\n"
        "        __Months,\n"
        "        VAR __MonthEnd = [__MonthEnd]\n"
        "        VAR __MonthStart = EOMONTH(__MonthEnd, -1) + 1\n"
        "        VAR __Availability =\n"
        f"            CALCULATE({measure}, DATESBETWEEN({date_column}, __MonthStart, __MonthEnd))\n"
        "        RETURN IF(NOT ISBLANK(__Availability), __Availability * DAY(__MonthEnd))\n"
        "    )\n"
        "VAR __AvailableDays =\n"
        "    SUMX(\n"
        "        __Months,\n"
        "        VAR __MonthEnd = [__MonthEnd]\n"
        "        VAR __MonthStart = EOMONTH(__MonthEnd, -1) + 1\n"
        "        VAR __Availability =\n"
        f"            CALCULATE({measure}, DATESBETWEEN({date_column}, __MonthStart, __MonthEnd))\n"
        "        RETURN IF(NOT ISBLANK(__Availability), DAY(__MonthEnd))\n"
        "    )\n"
        "RETURN DIVIDE(__WeightedAvailability, __AvailableDays)"
    )


def _summarize_dax(group_columns: list[str], filter_clauses: list[str], metric: dict) -> str:
    args = group_columns + filter_clauses + [
        f'"{metric["metric_label"]}", {metric["powerbi_measure_name"]}'
    ]
    return (
        "SUMMARIZECOLUMNS(\n"
        f"    {',\n    '.join(args)}\n"
        ")"
    )


def generate_dax_from_intent(intent: dict) -> dict:
    valid, errors = validate_intent(intent)
    if not valid:
        raise IntentValidationError("Invalid intent: " + "; ".join(errors))

    section_code = intent["section"]
    metric_code = intent["metric"]
    metric = next(item for item in get_metric_mapping(section_code) if item["metric_code"] == metric_code and item["is_active"])
    filters_config = {item["filter_code"]: item for item in get_filter_mapping(section_code) if item["is_active"]}
    filters = intent.get("filters") or {}
    filter_clauses = _filter_clauses(filters, filters_config)

    template = get_dax_template(section_code, "single_metric_by_filters") or get_dax_template(section_code)
    raw_intent_type = str(intent.get("intent_type") or "single_kpi")
    intent_type = {
        "trend_analysis": "trend",
        "entity_comparison": "comparison",
        "period_comparison": "comparison",
    }.get(raw_intent_type, raw_intent_type)
    comparison = intent.get("comparison") if isinstance(intent.get("comparison"), dict) else {}
    if intent_type == "trend":
        period_mapping = filters_config.get("period")
        if not period_mapping:
            raise IntentValidationError("Period mapping is required for an Availability trend.")
        group_columns = [
            _dax_column(period_mapping["powerbi_table_name"], "Year Month Number"),
            _dax_column(period_mapping["powerbi_table_name"], "Year Month"),
        ]
        dax = "EVALUATE\n" + _summarize_dax(group_columns, filter_clauses, metric)
        dax += f"\nORDER BY {_dax_column(period_mapping['powerbi_table_name'], 'Year Month Number')}"
    elif intent_type == "comparison":
        comparison_code = next(
            (
                code for code, values in comparison.items()
                if code in filters_config and isinstance(values, list) and values
            ),
            "",
        )
        if not comparison_code:
            raise IntentValidationError("A comparison requires at least two configured values.")
        comparison_values = comparison[comparison_code]
        if len(comparison_values) < 2:
            raise IntentValidationError("A comparison requires at least two values.")
        mapping = filters_config[comparison_code]
        comparison_filter = _build_filter_clause(mapping, comparison_values)
        group_column = _dax_column(mapping["powerbi_table_name"], mapping["powerbi_column_name"])
        dax = "EVALUATE\n" + _summarize_dax(
            [group_column],
            filter_clauses + [comparison_filter],
            metric,
        )
        dax += f"\nORDER BY {group_column}"
    elif intent_type == "ranking":
        dimension_code = str(comparison.get("dimension") or "model")
        mapping = filters_config.get(dimension_code)
        if not mapping:
            raise IntentValidationError(f"Ranking dimension '{dimension_code}' is not configured.")
        try:
            top_n = max(1, min(int(comparison.get("top_n") or 10), 50))
        except (TypeError, ValueError):
            top_n = 10
        direction = "DESC" if str(comparison.get("direction") or "").lower() == "desc" else "ASC"
        group_column = _dax_column(mapping["powerbi_table_name"], mapping["powerbi_column_name"])
        summarized = _summarize_dax([group_column], filter_clauses, metric)
        dax = (
            "EVALUATE\n"
            f"TOPN(\n    {top_n},\n    {summarized},\n"
            f"    [{metric['metric_label']}], {direction}\n"
            ")\n"
            f"ORDER BY [{metric['metric_label']}] {direction}"
        )
    else:
        is_availability_ytd = (
            metric_code == "availability"
            and _normalize(normalize_period_value(filters.get("period"))) == "year to date"
            and filters_config.get("period") is not None
        )
        metric_expression = (
            _report_aligned_availability_ytd_expression(metric, filters_config["period"])
            if is_availability_ytd
            else metric["powerbi_measure_name"]
        )
        if filter_clauses:
            dax = (
                "EVALUATE\n"
                "ROW(\n"
                f"    \"{metric['metric_label']}\",\n"
                "    CALCULATE(\n"
                f"        {metric_expression},\n"
                f"        {',\n        '.join(filter_clauses)}\n"
                "    )\n"
                ")"
            )
        else:
            dax = (
                "EVALUATE\n"
                "ROW(\n"
                f"    \"{metric['metric_label']}\", {metric['powerbi_measure_name']}\n"
                ")"
            )

    return {
        "section": section_code,
        "metric": metric_code,
        "metric_label": metric["metric_label"],
        "measure": metric["powerbi_measure_name"],
        "filters": filters,
        "dax": dax,
        "template_code": template["template_code"] if template else "default",
        "validation": {
            "valid": True,
            "errors": [],
        },
    }


def generate_performance_overview_dax(intent: dict) -> dict:
    section_code = str(intent.get("section") or "performance")
    metrics = [
        item for item in get_metric_mapping(section_code)
        if item.get("is_active") and item.get("metric_code") in {
            "availability", "mtbf", "mttr", "mtbs", "operating_hours", "downtime_hours"
        }
    ]
    if not metrics:
        raise IntentValidationError("No performance overview metrics are configured.")
    filters_config = {
        item["filter_code"]: item for item in get_filter_mapping(section_code)
        if item.get("is_active")
    }
    filters = intent.get("filters") or {}
    clauses = _filter_clauses(filters, filters_config)
    values = []
    for metric in metrics:
        expression = metric["powerbi_measure_name"]
        if clauses:
            expression = f"CALCULATE({expression}, {', '.join(clauses)})"
        values.extend((f'"{metric["metric_label"]}"', expression))
    dax = "EVALUATE\nROW(\n    " + ",\n    ".join(values) + "\n)"
    return {
        "section": section_code,
        "metric": "performance_overview",
        "metric_label": "Performance Overview",
        "measure": ", ".join(item["powerbi_measure_name"] for item in metrics),
        "filters": filters,
        "dax": dax,
        "template_code": "performance_overview",
    }


def generate_fleet_performance_dax(intent: dict) -> dict:
    """Build one governed query for a compositional Fleet Performance request."""
    section_code = str(intent.get("section") or "performance")
    intent_type = str(intent.get("intent_type") or "single_kpi")
    if intent_type == "pm_analysis":
        raise IntentValidationError(
            "PM Analysis is not fully configured: validated PM measures and filter mappings are required."
        )
    if intent_type in {"component_analysis", "down_hours_by_compartment"}:
        raise IntentValidationError(
            "The requested diagnostic is not fully configured: a validated downtime measure and dimension mapping are required."
        )
    filters_config = {
        item["filter_code"]: item
        for item in get_filter_mapping(section_code)
        if item.get("is_active")
    }
    filters = dict(intent.get("filters") or {})
    if intent_type == "smu_tracking":
        smu_mapping = filters_config.get("fleet_smu")
        identity_codes = ("fleet_site", "equipment", "model", "serial_number")
        identity_columns = [
            _dax_column(filters_config[code]["powerbi_table_name"], filters_config[code]["powerbi_column_name"])
            for code in identity_codes if code in filters_config
        ]
        if not smu_mapping or len(identity_columns) < 4:
            raise IntentValidationError("SMU Tracking is not fully configured.")
        smu_column = _dax_column(smu_mapping["powerbi_table_name"], smu_mapping["powerbi_column_name"])
        snapshot_filters = {key: value for key, value in filters.items() if key != "period"}
        clauses = _filter_clauses(snapshot_filters, filters_config)
        dax = (
            "EVALUATE\nSUMMARIZECOLUMNS(\n    "
            + ",\n    ".join(identity_columns + clauses + ['"SMU", MAX(' + smu_column + ')'])
            + "\n)\nORDER BY " + identity_columns[0] + ", " + identity_columns[1]
        )
        return {
            "section": section_code,
            "metric": "smu",
            "metrics": ["smu"],
            "metric_label": "SMU Tracking",
            "measure": f"MAX({smu_column})",
            "filters": filters,
            "dax": dax,
            "template_code": "PERF_SMU_TRACKING",
        }
    metric_codes = metrics_for_intent(intent)
    if not metric_codes:
        raise IntentValidationError("No governed Fleet Performance metric was resolved.")
    configured_metrics = {
        item["metric_code"]: item
        for item in get_metric_mapping(section_code)
        if item.get("is_active")
    }
    missing = [code for code in metric_codes if code not in configured_metrics]
    if missing:
        raise IntentValidationError(
            "The requested Fleet Performance KPI is not fully configured: " + ", ".join(missing)
        )
    metrics = [configured_metrics[code] for code in metric_codes]
    clauses = _filter_clauses(filters, filters_config)
    query_intent = str(intent.get("query_intent_type") or intent_type)

    metric_args = []
    for metric in metrics:
        metric_args.extend((f'"{metric["metric_label"]}"', metric["powerbi_measure_name"]))
    coverage_expressions = (
        ("Fleet Equipment", "DISTINCTCOUNT('EquipmentList_MiningProd'[SN])"),
        (
            "Equipment With Data",
            "COUNTROWS(FILTER(DISTINCT(UNION("
            "SELECTCOLUMNS('DowntimeData_MiningProd', \"__SN\", 'DowntimeData_MiningProd'[SN]), "
            "SELECTCOLUMNS('OperatingTime_MiningProd', \"__SN\", 'OperatingTime_MiningProd'[SN])"
            ")), NOT ISBLANK([__SN]) && [__SN] <> \"\"))",
        ),
    )
    for label, expression in coverage_expressions:
        metric_args.extend((f'"{label}"', expression))

    group_columns: list[str] = []
    extra_clauses: list[str] = []
    comparison = intent.get("comparison") if isinstance(intent.get("comparison"), dict) else {}
    if intent_type == "benchmark_analysis":
        site_mapping = filters_config.get("minesite")
        if not site_mapping:
            raise IntentValidationError("Benchmark Site mapping is not configured.")
        group_columns.append(_dax_column(site_mapping["powerbi_table_name"], site_mapping["powerbi_column_name"]))
        benchmark_filters = {key: value for key, value in filters.items() if key not in {"minesite", "site"}}
        clauses = _filter_clauses(benchmark_filters, filters_config)
    elif query_intent in {"comparison", "entity_comparison", "period_comparison"}:
        comparison_code = next(
            (
                code for code, values in comparison.items()
                if code in filters_config and isinstance(values, list) and len(values) >= 2
            ),
            "",
        )
        if comparison_code:
            mapping = filters_config[comparison_code]
            extra_clauses.append(_build_filter_clause(mapping, comparison[comparison_code]))
            group_columns.append(_dax_column(mapping["powerbi_table_name"], mapping["powerbi_column_name"]))
        elif intent.get("group_by"):
            code = str(intent["group_by"][0])
            mapping = filters_config.get(code)
            if mapping:
                group_columns.append(_dax_column(mapping["powerbi_table_name"], mapping["powerbi_column_name"]))
    elif query_intent in {"trend", "trend_analysis"}:
        period_mapping = filters_config.get("period")
        if not period_mapping:
            raise IntentValidationError("Period mapping is required for a Fleet Performance trend.")
        group_columns.extend((
            _dax_column(period_mapping["powerbi_table_name"], "Year Month Number"),
            _dax_column(period_mapping["powerbi_table_name"], "Year Month"),
        ))
    elif query_intent == "ranking":
        dimension_code = str(comparison.get("dimension") or (intent.get("group_by") or ["model"])[0])
        if dimension_code in {"equipment", "serial_number"}:
            for code in ("fleet_site", "equipment", "model", "serial_number"):
                mapping = filters_config.get(code)
                if mapping:
                    column = _dax_column(mapping["powerbi_table_name"], mapping["powerbi_column_name"])
                    if column not in group_columns:
                        group_columns.append(column)
        else:
            mapping = filters_config.get(dimension_code)
            if not mapping:
                raise IntentValidationError(f"Ranking dimension '{dimension_code}' is not configured.")
            group_columns.append(_dax_column(mapping["powerbi_table_name"], mapping["powerbi_column_name"]))

    if group_columns:
        args = group_columns + clauses + extra_clauses + metric_args
        summarized = "SUMMARIZECOLUMNS(\n    " + ",\n    ".join(args) + "\n)"
        if query_intent == "ranking":
            try:
                top_n = max(1, min(int(comparison.get("top_n") or 10), 100))
            except (TypeError, ValueError):
                top_n = 10
            direction = str(comparison.get("direction") or "asc").upper()
            direction = "DESC" if direction == "DESC" else "ASC"
            primary_label = metrics[0]["metric_label"]
            dax = f"EVALUATE\nTOPN({top_n}, {summarized}, [{primary_label}], {direction})\nORDER BY [{primary_label}] {direction}"
        else:
            dax = "EVALUATE\n" + summarized
            if query_intent in {"trend", "trend_analysis"}:
                dax += f"\nORDER BY {group_columns[0]}"
    else:
        values = []
        for metric in metrics:
            expression = metric["powerbi_measure_name"]
            if clauses:
                expression = f"CALCULATE({expression}, {', '.join(clauses)})"
            values.extend((f'"{metric["metric_label"]}"', expression))
        for label, coverage_expression in coverage_expressions:
            if clauses:
                coverage_expression = f"CALCULATE({coverage_expression}, {', '.join(clauses)})"
            values.extend((f'"{label}"', coverage_expression))
        dax = "EVALUATE\nROW(\n    " + ",\n    ".join(values) + "\n)"

    return {
        "section": section_code,
        "metric": metric_codes[0] if len(metric_codes) == 1 else "fleet_performance",
        "metrics": metric_codes,
        "metric_label": metrics[0]["metric_label"] if len(metrics) == 1 else "Fleet Performance",
        "measure": ", ".join(item["powerbi_measure_name"] for item in metrics),
        "filters": filters,
        "dax": dax,
        "template_code": {
            "trend_analysis": "PERF_MULTI_KPI_TREND" if len(metrics) > 1 else "PERF_KPI_TREND",
            "entity_comparison": "PERF_MULTI_KPI_BY_SITE" if len(metrics) > 1 else "PERF_KPI_BY_SITE",
            "ranking": "PERF_RANKING",
            "planned_unplanned_analysis": "PERF_DOWNTIME_MIX",
            "reliability_overview": "PERF_RELIABILITY_SUMMARY",
        }.get(intent_type, "PERF_CORE_KPI_SUMMARY" if len(metrics) > 1 else "PERF_SINGLE_KPI"),
    }
