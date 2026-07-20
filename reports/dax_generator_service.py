from __future__ import annotations

from datetime import date
import re

from .ai_config_service import get_dax_template, get_metric_mapping, get_filter_mapping, get_section_by_code


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
    text = str(value).strip().lower()
    date_column = _dax_column(mapping["powerbi_table_name"], "Date")
    if text == "year to date":
        return (
            f"DATESBETWEEN({date_column}, "
            "DATE(YEAR(TODAY()), 1, 1), TODAY())"
        )
    if text == "month to date":
        return (
            f"DATESBETWEEN({date_column}, "
            "DATE(YEAR(TODAY()), MONTH(TODAY()), 1), TODAY())"
        )
    if text in {"last 12 months", "douze derniers mois", "12 derniers mois"}:
        return f"DATESINPERIOD({date_column}, TODAY(), -12, MONTH)"
    if text in {"current month", "ce mois", "mois courant"}:
        today = date.today()
        return f"DATESBETWEEN({date_column}, DATE({today.year}, {today.month}, 1), EOMONTH(DATE({today.year}, {today.month}, 1), 0))"
    if text in {"previous month", "last month", "mois précédent", "mois precedent"}:
        today = date.today()
        return (
            f"DATESBETWEEN({date_column}, "
            f"EOMONTH(DATE({today.year}, {today.month}, 1), -2) + 1, "
            f"EOMONTH(DATE({today.year}, {today.month}, 1), -1))"
        )
    match = re.fullmatch(r"(20\d{2})", text)
    if match:
        year = int(match.group(1))
        return f"DATESBETWEEN({date_column}, DATE({year}, 1, 1), DATE({year}, 12, 31))"
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
    intent_type = str(intent.get("intent_type") or "single_kpi")
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
        if filter_clauses:
            dax = (
                "EVALUATE\n"
                "ROW(\n"
                f"    \"{metric['metric_label']}\",\n"
                "    CALCULATE(\n"
                f"        {metric['powerbi_measure_name']},\n"
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
