from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.core.cache import cache
from django.utils import timezone

from .ai_config_service import get_dax_template, get_filter_mapping, get_metric_mapping
from .models import (
    HomepageConfiguration,
    KnowledgeKPIDictionary,
    PlatformUser,
    PowerBIReport,
)
from .power_automate import PowerAutomateTransientError, execute_dax_via_flow
from .powerbi import get_access_token, get_latest_refresh_cached


LOGGER = logging.getLogger(__name__)
VALID_PERIODS = {"ytd", "last_12_months"}
VALID_BREAKDOWNS = {"overall", "minesite", "model", "equipment"}
VALID_ORDERING = {"availability_desc", "availability_asc", "downtime_desc", "name_asc"}
CUSTOMER_TYPE_TARGETS = {
    "do it for me": 0.85,
    "do it with me": 0.80,
    "do it myself": 0.75,
}
HOMEPAGE_PRODUCT_GROUP_CODES = ("HMS", "LMT", "LWL", "OHT")
HOMEPAGE_PRODUCT_GROUP_CODES = ("HMS", "LMT", "LWL", "OHT")


class HomepageAvailabilityError(RuntimeError):
    def __init__(self, message: str, *, code: str = "availability_unavailable", status: int = 503):
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class HomepageRequest:
    period: str
    breakdown: str
    filters: dict[str, str]
    page: int
    page_size: int
    ordering: str
    query: str


def _clean_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _row_value(row: dict, *names: str):
    values = {_clean_key(key): value for key, value in (row or {}).items()}
    for name in names:
        if _clean_key(name) in values:
            return values[_clean_key(name)]
    return None


def _extract_rows(payload) -> list[dict]:
    if isinstance(payload, list):
        direct = [item for item in payload if isinstance(item, dict)]
        if direct:
            return direct
        return []
    if not isinstance(payload, dict):
        return []
    rows = payload.get("firstTableRows")
    if isinstance(rows, list):
        return [item for item in rows if isinstance(item, dict)]
    try:
        rows = payload["results"][0]["tables"][0]["rows"]
        if isinstance(rows, list):
            return [item for item in rows if isinstance(item, dict)]
    except (KeyError, IndexError, TypeError):
        pass
    for key in ("rows", "results", "body", "value"):
        rows = _extract_rows(payload.get(key))
        if rows:
            return rows
    return []


def _as_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _date_value(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        try:
            return date(1899, 12, 30) + timedelta(days=int(value))
        except (OverflowError, ValueError):
            return None
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"(20\d{2})-(\d{2})-(\d{2})", text)
    if match:
        try:
            return date(*map(int, match.groups()))
        except ValueError:
            return None
    match = re.search(r"Date\((\d{4}),\s*(\d{1,2}),\s*(\d{1,2})", text)
    if match:
        try:
            return date(*map(int, match.groups()))
        except ValueError:
            return None
    return None


def _period_start(latest_date: date | None, period: str) -> date | None:
    if not latest_date:
        return None
    if period == "ytd":
        return date(latest_date.year, 1, 1)
    month_index = latest_date.year * 12 + latest_date.month - 12
    year, month_zero_based = divmod(month_index, 12)
    return date(year, month_zero_based + 1, 1)


def _dax_string(value: object) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def _dax_column(table: str, column: str) -> str:
    escaped_table = str(table).replace("'", "''")
    escaped_column = str(column).replace("]", "]]" )
    return f"'{escaped_table}'[{escaped_column}]"


def _format_percent(value) -> str | None:
    number = _as_float(value)
    return f"{number * 100:.2f}%" if number is not None else None


def _format_points(value) -> float | None:
    number = _as_float(value)
    return round(number * 100, 2) if number is not None else None


class HomepageAvailabilityService:
    DATASET_NAME = "FPR Global DB + RLS"
    SECTION_CODE = "performance"
    FILTER_KEYS = ("customer", "minesite", "model", "family", "equipment", "serial_number")

    def __init__(self, user=None):
        self.user = user
        self.config = HomepageConfiguration.objects.filter(active=True).order_by("id").first()
        if not self.config:
            self.config = HomepageConfiguration(code="availability-command-center")
        self.metric = self._resolve_metric()
        self.kpi = self._resolve_kpi()
        self.filter_mappings = {
            item["filter_code"]: item
            for item in get_filter_mapping(self.SECTION_CODE)
            if item.get("is_active")
        }
        self.report = self._resolve_report()

    def _resolve_metric(self) -> dict:
        metric = next(
            (
                item for item in get_metric_mapping(self.SECTION_CODE)
                if item.get("is_active") and item.get("metric_code") == "availability"
            ),
            None,
        )
        if not metric or not str(metric.get("powerbi_measure_name") or "").strip():
            raise HomepageAvailabilityError(
                "Physical Availability is not configured in Metrics Mapping.",
                code="availability_mapping_missing",
                status=503,
            )
        return metric

    def _resolve_kpi(self):
        return (
            KnowledgeKPIDictionary.objects.filter(
                section__code=self.SECTION_CODE,
                kpi_code="availability",
                validation_status="Validated",
                is_active=True,
            )
            .order_by("-updated_at")
            .first()
        )

    def _resolve_report(self):
        dataset_id = str(getattr(self.kpi, "powerbi_semantic_model_id", "") or "").strip()
        queryset = PowerBIReport.objects.filter(is_active=True)
        report = queryset.filter(semantic_model_id=dataset_id).order_by("id").first() if dataset_id else None
        if not report:
            report = queryset.filter(report_name__iexact=self.DATASET_NAME).order_by("id").first()
        if not report:
            raise HomepageAvailabilityError(
                "The Fleet Performance Semantic Model is not configured.",
                code="semantic_model_missing",
                status=503,
            )
        return report

    def request_from_params(self, params) -> HomepageRequest:
        period = str(params.get("period") or self.config.default_period or "ytd").strip().casefold()
        breakdown = str(params.get("breakdown") or self.config.default_breakdown or "overall").strip().casefold()
        if period not in VALID_PERIODS:
            raise HomepageAvailabilityError("Unsupported period.", code="invalid_period", status=400)
        if breakdown not in VALID_BREAKDOWNS:
            raise HomepageAvailabilityError("Unsupported breakdown.", code="invalid_breakdown", status=400)
        filters = {
            key: str(params.get(key) or "").strip()
            for key in self.FILTER_KEYS
            if str(params.get(key) or "").strip()
        }
        try:
            page = max(1, int(params.get("page") or 1))
        except (TypeError, ValueError):
            page = 1
        configured_page_size = max(10, min(int(self.config.equipment_page_size or 25), 100))
        try:
            page_size = max(10, min(int(params.get("page_size") or configured_page_size), 100))
        except (TypeError, ValueError):
            page_size = configured_page_size
        ordering = str(params.get("ordering") or "availability_desc").strip().casefold()
        if ordering not in VALID_ORDERING:
            ordering = "availability_desc"
        query = str(params.get("q") or "").strip()[:120]
        return HomepageRequest(period, breakdown, filters, page, page_size, ordering, query)

    def _platform_user(self):
        try:
            return self.user.platformuser
        except (AttributeError, PlatformUser.DoesNotExist):
            return None

    def _scope(self) -> tuple[dict, str, str]:
        platform_user = self._platform_user()
        if not platform_user or platform_user.is_platform_admin:
            return {}, "", ""
        raw_scope = platform_user.business_performance_scope or {}
        scope = {}
        for code in ("customer", "minesite"):
            values = raw_scope.get(code)
            if values:
                scope[code] = values if isinstance(values, list) else [values]
        rls_role = str(raw_scope.get("rls_role") or "").strip()
        effective_user = str(platform_user.user_principal_name or platform_user.email or "").strip()
        return scope, rls_role, effective_user

    @staticmethod
    def _merge_filters(scope: dict, requested: dict) -> dict:
        merged = {key: list(value) if isinstance(value, list) else [value] for key, value in scope.items()}
        for key, value in requested.items():
            if key in merged:
                allowed = {str(item).casefold(): str(item) for item in merged[key]}
                if str(value).casefold() not in allowed:
                    raise HomepageAvailabilityError(
                        "You do not have access to the selected scope.",
                        code="scope_forbidden",
                        status=403,
                    )
            merged[key] = [value]
        return merged

    def _filter_clauses(self, filters: dict) -> list[str]:
        clauses = []
        for code, values in filters.items():
            mapping = self.filter_mappings.get(code)
            if not mapping:
                continue
            items = values if isinstance(values, list) else [values]
            literals = ", ".join(_dax_string(item) for item in items if str(item).strip())
            if literals:
                clauses.append(
                    f"TREATAS({{{literals}}}, "
                    f"{_dax_column(mapping['powerbi_table_name'], mapping['powerbi_column_name'])})"
                )
        return clauses

    def _dimension_columns(self, breakdown: str) -> tuple[str, list[tuple[str, str]]]:
        dimension = "minesite" if breakdown == "overall" else breakdown
        if dimension == "equipment":
            equipment = self.filter_mappings.get("equipment")
            model = self.filter_mappings.get("model")
            site = self.filter_mappings.get("minesite")
            if not equipment:
                raise HomepageAvailabilityError("Equipment mapping is missing.", code="dimension_mapping_missing")
            extras = []
            if model:
                extras.append(("Model", _dax_column(model["powerbi_table_name"], model["powerbi_column_name"])))
            if site:
                extras.append(("MineSite", _dax_column(site["powerbi_table_name"], site["powerbi_column_name"])))
            return _dax_column(equipment["powerbi_table_name"], equipment["powerbi_column_name"]), extras
        mapping = self.filter_mappings.get(dimension)
        if not mapping:
            raise HomepageAvailabilityError(
                f"The {dimension} mapping is missing.",
                code="dimension_mapping_missing",
            )
        return _dax_column(mapping["powerbi_table_name"], mapping["powerbi_column_name"]), []

    def build_dax(self, request: HomepageRequest, merged_filters: dict) -> str:
        measure = str(self.metric["powerbi_measure_name"]).strip()
        downtime_metric = next(
            (
                item for item in get_metric_mapping(self.SECTION_CODE)
                if item.get("is_active") and item.get("metric_code") == "downtime_hours"
            ),
            None,
        )
        downtime_measure = str((downtime_metric or {}).get("powerbi_measure_name") or "BLANK()").strip()
        date_column = _dax_column("Date", "Date")
        month_number_column = _dax_column("Date", "Year Month Number")
        month_label_column = _dax_column("Date", "Year Month")
        serial = self.filter_mappings.get("serial_number")
        site = self.filter_mappings.get("minesite")
        serial_column = (
            _dax_column(serial["powerbi_table_name"], serial["powerbi_column_name"])
            if serial else "BLANK()"
        )
        site_column = (
            _dax_column(site["powerbi_table_name"], site["powerbi_column_name"])
            if site else "BLANK()"
        )
        model_mapping = self.filter_mappings.get("model")
        model_column = (
            _dax_column(model_mapping["powerbi_table_name"], model_mapping["powerbi_column_name"])
            if model_mapping else "BLANK()"
        )
        equipment_mapping = self.filter_mappings.get("equipment")
        equipment_column = (
            _dax_column(equipment_mapping["powerbi_table_name"], equipment_mapping["powerbi_column_name"])
            if equipment_mapping else "BLANK()"
        )
        product_group_mapping = self.filter_mappings.get("homepage_product_group") or {
            "powerbi_table_name": "ModelList_MiningProd",
            "powerbi_column_name": "PrimeMovers",
        }
        model_reference_mapping = self.filter_mappings.get("homepage_model_reference") or {
            "powerbi_table_name": "ModelList_MiningProd",
            "powerbi_column_name": "Model",
        }
        product_group_column = _dax_column(
            product_group_mapping["powerbi_table_name"],
            product_group_mapping["powerbi_column_name"],
        )
        model_reference_column = _dax_column(
            model_reference_mapping["powerbi_table_name"],
            model_reference_mapping["powerbi_column_name"],
        )
        allowed_group_literals = ", ".join(_dax_string(code) for code in HOMEPAGE_PRODUCT_GROUP_CODES)
        allowed_model_filter = f"TREATAS(__AllowedModels, {model_column})"
        product_group_mapping = self.filter_mappings.get("homepage_product_group") or {
            "powerbi_table_name": "ModelList_MiningProd",
            "powerbi_column_name": "PrimeMovers",
        }
        model_reference_mapping = self.filter_mappings.get("homepage_model_reference") or {
            "powerbi_table_name": "ModelList_MiningProd",
            "powerbi_column_name": "Model",
        }
        product_group_column = _dax_column(
            product_group_mapping["powerbi_table_name"],
            product_group_mapping["powerbi_column_name"],
        )
        model_reference_column = _dax_column(
            model_reference_mapping["powerbi_table_name"],
            model_reference_mapping["powerbi_column_name"],
        )
        allowed_group_literals = ", ".join(_dax_string(code) for code in HOMEPAGE_PRODUCT_GROUP_CODES)
        allowed_model_filter = f"TREATAS(__AllowedModels, {model_column})"
        focus_mapping = self.filter_mappings.get("focus") or {
            "powerbi_table_name": "MineSiteList_MiningProd",
            "powerbi_column_name": "Focus",
        }
        customer_type_mapping = self.filter_mappings.get("customer_type") or {
            "powerbi_table_name": "MineSiteList_MiningProd",
            "powerbi_column_name": "CustomerType",
        }
        focus_column = _dax_column(
            focus_mapping["powerbi_table_name"], focus_mapping["powerbi_column_name"]
        )
        customer_type_column = _dax_column(
            customer_type_mapping["powerbi_table_name"], customer_type_mapping["powerbi_column_name"]
        )
        filters = [f'TREATAS({{"Yes"}}, {focus_column})', *self._filter_clauses(merged_filters)]
        if request.breakdown in {"model", "equipment"} or "model" in merged_filters:
            filters.append(allowed_model_filter)
        if request.breakdown in {"model", "equipment"} or "model" in merged_filters:
            filters.append(allowed_model_filter)
        filter_args = (",\n            " + ",\n            ".join(filters)) if filters else ""
        latest_filter_args = (", " + ", ".join(filters)) if filters else ""
        if request.period == "ytd":
            start_expression = "DATE(YEAR(__LatestDate), 1, 1)"
            previous_start = "DATE(YEAR(__LatestDate) - 1, 1, 1)"
            previous_end = "EDATE(__LatestDate, -12)"
        else:
            start_expression = "EOMONTH(__LatestDate, -12) + 1"
            previous_start = "EOMONTH(__LatestDate, -24) + 1"
            previous_end = "EOMONTH(__LatestDate, -12)"
        dimension_column, extras = self._dimension_columns(request.breakdown)
        grouping = [dimension_column, *[column for _, column in extras]]
        group_lines = ",\n        ".join(grouping)
        extra_select = ""
        extra_blank = ""
        for index, (label, column) in enumerate(extras, start=1):
            extra_select += f',\n        "Extra{index}", {column}'
        for index in range(len(extras) + 1, 3):
            extra_select += f',\n        "Extra{index}", BLANK()'
        extra_blank = ',\n        "Extra1", BLANK(),\n        "Extra2", BLANK()'
        search_filter = ""
        if request.query and request.breakdown == "equipment":
            search_filter = (
                "\nVAR __FilteredBreakdown = FILTER(__Breakdown, "
                f"CONTAINSSTRING(LOWER([Entity]), LOWER({_dax_string(request.query)})))"
            )
            breakdown_result = "__FilteredBreakdown"
        else:
            breakdown_result = "__Breakdown"
        generated_query = f"""
DEFINE
VAR __AllowedModels =
    CALCULATETABLE(
        VALUES({model_reference_column}),
        TREATAS({{{allowed_group_literals}}}, {product_group_column})
    )
VAR __LatestDataDate =
    MAXX(
        FILTER(
            CALCULATETABLE(ALL({date_column}){latest_filter_args}),
            NOT ISBLANK(CALCULATE({measure}{latest_filter_args}))
        ),
        {date_column}
    )
VAR __LatestDate = EOMONTH(__LatestDataDate, 0)
VAR __StartDate = {start_expression}
VAR __PreviousStart = {previous_start}
VAR __PreviousEnd = {previous_end}
VAR __CurrentPeriod = DATESBETWEEN({date_column}, __StartDate, __LatestDate)
VAR __PreviousPeriod = DATESBETWEEN({date_column}, __PreviousStart, __PreviousEnd)
VAR __Summary =
    ROW(
        "RowType", "summary",
        "Entity", "Overall",
        "SortKey", "",
        "Availability", CALCULATE({measure}, __CurrentPeriod{filter_args}),
        "PreviousAvailability", CALCULATE({measure}, __PreviousPeriod{filter_args}),
        "EquipmentCount", CALCULATE(DISTINCTCOUNT({serial_column}), __CurrentPeriod{filter_args}),
        "MineSiteCount", CALCULATE(DISTINCTCOUNT({site_column}), __CurrentPeriod{filter_args}),
        "DowntimeHours", CALCULATE({downtime_measure}, __CurrentPeriod{filter_args}),
        "LatestDate", __LatestDate,
        "CustomerType", CALCULATE(SELECTEDVALUE({customer_type_column}), __CurrentPeriod{filter_args}){extra_blank}
    )
VAR __TrendBase =
    SUMMARIZECOLUMNS(
        {month_number_column},
        {month_label_column},
        __CurrentPeriod{filter_args},
        "Availability", {measure}
    )
VAR __Trend =
    SELECTCOLUMNS(
        __TrendBase,
        "RowType", "trend",
        "Entity", {month_label_column},
        "SortKey", {month_number_column},
        "Availability", [Availability],
        "PreviousAvailability", BLANK(),
        "EquipmentCount", BLANK(),
        "MineSiteCount", BLANK(),
        "DowntimeHours", BLANK(),
        "LatestDate", BLANK(),
        "CustomerType", BLANK(){extra_blank}
    )
VAR __BreakdownBase =
    SUMMARIZECOLUMNS(
        {group_lines},
        __CurrentPeriod{filter_args},
        "Availability", {measure},
        "DowntimeHours", {downtime_measure},
        "EquipmentCount", DISTINCTCOUNT({serial_column}),
        "CustomerType", SELECTEDVALUE({customer_type_column})
    )
VAR __Breakdown =
    SELECTCOLUMNS(
        FILTER(__BreakdownBase, NOT ISBLANK([Availability])),
        "RowType", "breakdown",
        "Entity", {dimension_column},
        "SortKey", "",
        "Availability", [Availability],
        "PreviousAvailability", BLANK(),
        "EquipmentCount", [EquipmentCount],
        "MineSiteCount", BLANK(),
        "DowntimeHours", [DowntimeHours],
        "LatestDate", BLANK(),
        "CustomerType", [CustomerType]{extra_select}
    ){search_filter}
VAR __MineSiteOptions =
    SELECTCOLUMNS(
        SUMMARIZECOLUMNS({site_column}, __CurrentPeriod{filter_args}),
        "RowType", "option_minesite",
        "Entity", {site_column},
        "SortKey", "",
        "Availability", BLANK(),
        "PreviousAvailability", BLANK(),
        "EquipmentCount", BLANK(),
        "MineSiteCount", BLANK(),
        "DowntimeHours", BLANK(),
        "LatestDate", BLANK(),
        "CustomerType", BLANK(){extra_blank}
    )
VAR __ModelOptionsBase =
    SUMMARIZECOLUMNS(
        {model_column},
        __CurrentPeriod{filter_args},
        {allowed_model_filter},
        "OptionAvailability", {measure}
    )
VAR __ModelOptions =
    SELECTCOLUMNS(
        FILTER(__ModelOptionsBase, NOT ISBLANK([OptionAvailability])),
        "RowType", "option_model",
        "Entity", {model_column},
        "SortKey", "",
        "Availability", BLANK(),
        "PreviousAvailability", BLANK(),
        "EquipmentCount", BLANK(),
        "MineSiteCount", BLANK(),
        "DowntimeHours", BLANK(),
        "LatestDate", BLANK(),
        "CustomerType", BLANK(){extra_blank}
    )
VAR __EquipmentOptionsBase =
    SUMMARIZECOLUMNS(
        {equipment_column},
        __CurrentPeriod{filter_args},
        {allowed_model_filter},
        "OptionAvailability", {measure}
    )
VAR __EquipmentOptions =
    SELECTCOLUMNS(
        FILTER(__EquipmentOptionsBase, NOT ISBLANK([OptionAvailability])),
        "RowType", "option_equipment",
        "Entity", {equipment_column},
        "SortKey", "",
        "Availability", BLANK(),
        "PreviousAvailability", BLANK(),
        "EquipmentCount", BLANK(),
        "MineSiteCount", BLANK(),
        "DowntimeHours", BLANK(),
        "LatestDate", BLANK(),
        "CustomerType", BLANK(){extra_blank}
    )
EVALUATE
UNION(__Summary, __Trend, {breakdown_result}, __MineSiteOptions, __ModelOptions, __EquipmentOptions)
""".strip()
        template = get_dax_template(self.SECTION_CODE, "HOME_AVAILABILITY_COMMAND_CENTER")
        if not template:
            return generated_query
        definitions, separator, result = generated_query.partition("\nEVALUATE\n")
        configured = str(template.get("dax_template") or "")
        if not separator or "{{QUERY_DEFINITIONS}}" not in configured or "{{QUERY_RESULT}}" not in configured:
            raise HomepageAvailabilityError(
                "The homepage DAX template is invalid.",
                code="homepage_dax_template_invalid",
                status=503,
            )
        return (
            configured
            .replace("{{QUERY_DEFINITIONS}}", definitions)
            .replace("{{QUERY_RESULT}}", result)
            .strip()
        )

    def _cache_key(self, request: HomepageRequest, scope: dict, rls_role: str) -> str:
        payload = {
            "user": getattr(self.user, "pk", None),
            "scope": scope,
            "role": rls_role,
            "period": request.period,
            "breakdown": request.breakdown,
            "filters": request.filters,
            "q": request.query,
            "metric": self.metric.get("powerbi_measure_name"),
            "dataset": self.report.semantic_model_id,
            "config": getattr(self.config, "updated_at", None).isoformat() if getattr(self.config, "updated_at", None) else "default",
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()
        return f"homepage:availability:v2:{digest}"

    def _refresh_metadata(self) -> tuple[str, str]:
        try:
            token = get_access_token()
            return get_latest_refresh_cached(
                token,
                self.report.workspace_id,
                self.report.semantic_model_id,
                cache_seconds=max(60, int(self.config.cache_duration_seconds or 300)),
            )
        except Exception as exc:
            LOGGER.warning("Homepage refresh metadata unavailable: %s", exc)
            return "", "Unavailable"

    def _execute(self, dax: str, merged_filters: dict, rls_role: str, effective_user: str) -> tuple[list[dict], dict]:
        payload = {
            "datasetId": self.report.semantic_model_id,
            "datasetName": self.DATASET_NAME,
            "query": dax,
            "question": "Mining 360 Availability Command Center",
            "section": self.SECTION_CODE,
            "metric": "availability",
            "measure": self.metric["powerbi_measure_name"],
            "filters": merged_filters,
            "rlsRole": rls_role,
            "roles": [rls_role] if rls_role else [],
            "effectiveUser": effective_user,
        }
        try:
            result = execute_dax_via_flow(payload)
        except PowerAutomateTransientError as exc:
            raise HomepageAvailabilityError(
                "Fleet performance data is temporarily unavailable.",
                code="powerbi_temporarily_unavailable",
                status=503,
            ) from exc
        except Exception as exc:
            LOGGER.exception("Homepage Availability execution failed")
            raise HomepageAvailabilityError(
                "Fleet performance data could not be loaded.",
                code="powerbi_execution_failed",
                status=503,
            ) from exc
        return _extract_rows(result), result

    @staticmethod
    def _customer_type_target(customer_type: object) -> float | None:
        normalized = re.sub(r"\s+", " ", str(customer_type or "").strip().casefold())
        return CUSTOMER_TYPE_TARGETS.get(normalized)

    def _status(self, value: float | None, target: float | None) -> tuple[str | None, float | None]:
        if value is None or target is None or not self.config.show_target:
            return None, None
        if value >= target:
            status = "on_target"
        else:
            status = "below_target"
        return status, round((value - target) * 100, 2)

    def _normalize(self, rows: list[dict], request: HomepageRequest, *, cached: bool, elapsed_ms: int) -> dict:
        summary_row = next((row for row in rows if str(_row_value(row, "RowType") or "").casefold() == "summary"), {})
        source_value = _as_float(_row_value(summary_row, "Availability"))
        source_previous_value = _as_float(_row_value(summary_row, "PreviousAvailability"))
        value_is_valid = source_value is None or 0 <= source_value <= 1
        previous_is_valid = source_previous_value is None or 0 <= source_previous_value <= 1
        value = source_value if value_is_valid else None
        previous_value = source_previous_value if previous_is_valid else None
        customer_type = str(_row_value(summary_row, "CustomerType") or "").strip()
        contextual_target = self._customer_type_target(customer_type)
        invalid_breakdown_count = 0
        invalid_trend_count = 0
        latest_date = _date_value(_row_value(summary_row, "LatestDate"))
        status, gap = self._status(value, contextual_target)
        if not value_is_valid:
            status = "data_quality_issue"
        comparison_delta = (
            round((value - previous_value) * 100, 2)
            if value is not None and previous_value is not None else None
        )
        trend = []
        breakdown = []
        filter_options = {"minesite": [], "model": [], "equipment": []}
        for row in rows:
            row_type = str(_row_value(row, "RowType") or "").casefold()
            item_value = _as_float(_row_value(row, "Availability"))
            if row_type == "trend" and item_value is not None and 0 <= item_value <= 1:
                trend.append({
                    "period": str(_row_value(row, "Entity") or ""),
                    "sort_key": str(_row_value(row, "SortKey") or ""),
                    "value": item_value,
                    "formatted_value": _format_percent(item_value),
                })
            elif row_type == "trend" and item_value is not None:
                invalid_trend_count += 1
            elif row_type == "breakdown" and item_value is not None:
                entity = str(_row_value(row, "Entity") or "").strip()
                if not entity:
                    continue
                item_is_valid = 0 <= item_value <= 1
                if item_is_valid:
                    item_customer_type = str(_row_value(row, "CustomerType") or "").strip()
                    item_target = self._customer_type_target(item_customer_type)
                    item_status, item_gap = self._status(item_value, item_target)
                else:
                    invalid_breakdown_count += 1
                    item_customer_type = str(_row_value(row, "CustomerType") or "").strip()
                    item_target = self._customer_type_target(item_customer_type)
                    item_status, item_gap = "data_quality_issue", None
                breakdown.append({
                    "entity": entity,
                    "availability": item_value if item_is_valid else None,
                    "source_raw_value": item_value,
                    "formatted_value": _format_percent(item_value) if item_is_valid else "Invalid data",
                    "quality_status": "valid" if item_is_valid else "out_of_range",
                    "customer_type": item_customer_type,
                    "target_raw": item_target,
                    "target_formatted": _format_percent(item_target),
                    "gap_points": item_gap,
                    "status": item_status,
                    "equipment_count": _as_int(_row_value(row, "EquipmentCount")),
                    "downtime_hours": _as_float(_row_value(row, "DowntimeHours")),
                    "model": str(_row_value(row, "Extra1") or ""),
                    "minesite": str(_row_value(row, "Extra2") or ""),
                })
            elif row_type in {"option_minesite", "option_model", "option_equipment"}:
                value_label = str(_row_value(row, "Entity") or "").strip()
                option_code = row_type.removeprefix("option_")
                if value_label and value_label not in filter_options[option_code]:
                    filter_options[option_code].append(value_label)
        for values in filter_options.values():
            values.sort(key=str.casefold)
        trend.sort(key=lambda item: item["sort_key"])
        if request.ordering == "availability_asc":
            breakdown.sort(key=lambda item: item["availability"] if item["availability"] is not None else float("inf"))
        elif request.ordering == "downtime_desc":
            breakdown.sort(key=lambda item: item["downtime_hours"] or 0, reverse=True)
        elif request.ordering == "name_asc":
            breakdown.sort(key=lambda item: item["entity"].casefold())
        else:
            breakdown.sort(key=lambda item: item["availability"] if item["availability"] is not None else float("-inf"), reverse=True)
        total_breakdown = len(breakdown)
        if request.breakdown == "equipment":
            start = (request.page - 1) * request.page_size
            page_breakdown = breakdown[start:start + request.page_size]
        else:
            page_breakdown = breakdown
        ranked = sorted(
            (item for item in breakdown if item["availability"] is not None),
            key=lambda item: item["availability"],
            reverse=True,
        )
        maximum_cards = max(3, min(int(self.config.maximum_cards or 5), 8))
        top = ranked[:maximum_cards] if self.config.show_top_performers else []
        bottom = list(reversed(ranked[-maximum_cards:])) if self.config.show_bottom_performers else []
        if not value_is_valid:
            takeaway = "The Semantic Model returned an out-of-range Physical Availability value. Data-quality review is required."
        elif value is None:
            takeaway = "No Physical Availability data is available for the selected context."
        elif ranked:
            takeaway = (
                f"Physical Availability is {_format_percent(value)}. "
                f"{ranked[0]['entity']} leads the selected scope at {ranked[0]['formatted_value']}, "
                f"while {ranked[-1]['entity']} requires attention at {ranked[-1]['formatted_value']}."
            )
        else:
            takeaway = f"Physical Availability is {_format_percent(value)} for the selected context."
        refresh_display, refresh_status = self._refresh_metadata()
        refresh_dt = None
        try:
            refresh_dt = timezone.make_aware(
                datetime.strptime(refresh_display, "%Y-%m-%d %I:%M %p"),
                timezone.get_current_timezone(),
            )
        except (TypeError, ValueError):
            refresh_dt = None
        stale = bool(
            refresh_dt
            and timezone.now() - refresh_dt
            > timedelta(hours=max(1, int(self.config.freshness_threshold_hours or 24)))
        )
        period_label = "Year to Date" if request.period == "ytd" else "Last 12 Months"
        return {
            "ok": True,
            "context": {
                "metric_code": "availability",
                "metric_label": self.metric.get("metric_label") or "Physical Availability",
                "period_code": request.period,
                "period_label": period_label,
                "start_date": _period_start(latest_date, request.period).isoformat() if latest_date else None,
                "end_date": latest_date.isoformat() if latest_date else None,
                "breakdown": request.breakdown,
                "filters": request.filters,
            },
            "availability": {
                "raw_value": value,
                "source_raw_value": source_value,
                "formatted_value": _format_percent(value) if value_is_valid else "Invalid data",
                "quality_status": "valid" if value_is_valid else "out_of_range",
                "customer_type": customer_type,
                "target_raw": contextual_target if self.config.show_target else None,
                "target_formatted": _format_percent(contextual_target) if self.config.show_target else None,
                "gap_points": gap,
                "status": status,
                "comparison": {
                    "label": "vs same period last year" if request.period == "ytd" else "vs previous rolling 12 months",
                    "previous_raw": previous_value,
                    "previous_formatted": _format_percent(previous_value),
                    "delta_points": comparison_delta,
                } if self.config.show_comparison and value is not None and previous_value is not None else None,
            },
            "trend": trend,
            "summary": {
                "minesite_count": _as_int(_row_value(summary_row, "MineSiteCount")),
                "equipment_count": _as_int(_row_value(summary_row, "EquipmentCount")),
                "calendar_hours": None,
                "available_hours": None,
                "downtime_hours": _as_float(_row_value(summary_row, "DowntimeHours")),
            },
            "breakdown": page_breakdown,
            "filter_options": filter_options,
            "breakdown_pagination": {
                "page": request.page,
                "page_size": request.page_size,
                "count": total_breakdown,
                "pages": max(1, (total_breakdown + request.page_size - 1) // request.page_size),
            },
            "top_performers": top,
            "bottom_performers": bottom,
            "key_takeaway": takeaway,
            "data_quality": {
                "latest_available_date": latest_date.isoformat() if latest_date else None,
                "last_refresh_at": refresh_display or None,
                "refresh_status": refresh_status,
                "is_stale": stale,
                "completeness": None,
            },
            "available_actions": [
                {"code": "ask_ai", "label": "Ask Mining 360 AI"},
                {"code": "view_downtime_drivers", "label": "View Downtime Drivers"},
                {"code": "open_report", "label": "Open Fleet Performance Report"},
            ],
            "warnings": [
                message
                for message in (
                    "The Semantic Model returned an out-of-range summary Availability value."
                    if not value_is_valid else "",
                    f"{invalid_trend_count} out-of-range trend value(s) were excluded."
                    if invalid_trend_count else "",
                    f"{invalid_breakdown_count} out-of-range breakdown value(s) require data-quality review."
                    if invalid_breakdown_count else "",
                )
                if message
            ],
            "ui": {
                "animation_enabled": bool(self.config.animation_enabled),
                "animation_intensity": self.config.animation_intensity,
                "maximum_cards": maximum_cards,
                "show_ai_insight": bool(self.config.show_ai_insight),
            },
            "meta": {
                "cached": cached,
                "duration_ms": elapsed_ms,
                "source": "powerbi_semantic_model",
                "dax_template": "HOME_AVAILABILITY_COMMAND_CENTER",
            },
        }

    def get(self, request: HomepageRequest) -> dict:
        scope, rls_role, effective_user = self._scope()
        merged_filters = self._merge_filters(scope, request.filters)
        cache_key = self._cache_key(request, scope, rls_role)
        cached_payload = cache.get(cache_key)
        if cached_payload is not None:
            payload = dict(cached_payload)
            payload["meta"] = {**(payload.get("meta") or {}), "cached": True}
            return payload
        started = time.monotonic()
        dax = self.build_dax(request, merged_filters)
        rows, _ = self._execute(dax, merged_filters, rls_role, effective_user)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        payload = self._normalize(rows, request, cached=False, elapsed_ms=elapsed_ms)
        cache.set(cache_key, payload, max(30, int(self.config.cache_duration_seconds or 300)))
        return payload
