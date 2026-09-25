from __future__ import annotations

import hashlib
import json
import math
import time
from datetime import date, datetime, timedelta

from django.core.cache import cache
from django.utils import timezone

from .homepage_availability_service import (
    HomepageAvailabilityError,
    HomepageRequest,
    _as_float,
    _as_int,
    _date_value,
    _dax_column,
    _dax_string,
    _extract_rows,
    _period_start,
    _row_value,
)
from .models import HomepageConfiguration, PlatformUser, PowerBIReport
from .power_automate import PowerAutomateTransientError, execute_dax_via_flow
from .powerbi import get_access_token, get_latest_refresh_cached
from .performance_periods import bounds, dax_window, context as period_context


FUEL_SITE_ALIASES = {
    "essakane": "IAMGOLD Essakane",
    "iamgold essakane": "IAMGOLD Essakane",
    "fekola": "B2Gold Fekola",
    "b2gold fekola": "B2Gold Fekola",
    "sangaredi/cbg": "CBG Sangaredi",
    "cbg sangaredi": "CBG Sangaredi",
    "siguiri": "AngloGold Ashanti Siguiri",
    "anglogold ashanti siguiri": "AngloGold Ashanti Siguiri",
}


def _fuel_site(value: object) -> str:
    text = str(value or "").strip()
    return FUEL_SITE_ALIASES.get(text.casefold(), text)


def _format_lph(value) -> str | None:
    number = _as_float(value)
    return f"{number:,.1f} L/h" if number is not None else None


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


class HomepageFuelService:
    DATASET_NAME = "Fuel Monitoring Report V1"
    MEASURE = "[Mean LPH]"
    DATE_COLUMN = ("FuelData", "AssetLocalDate")
    SITE_COLUMN = ("MineSiteList_MiningProd", "SiteGroup FPR")
    MODEL_COLUMN = ("ModelList_MiningProd", "Model")
    EQUIPMENT_COLUMN = ("EquipmentList_MiningProd", "Equipment")
    FAMILY_COLUMN = ("EquipmentList_MiningProd", "ParentProductGroup")
    VALID_PERIODS = {"ytd", "last_12_months"}

    def __init__(self, user=None):
        self.user = user
        self.config = HomepageConfiguration.objects.filter(active=True).order_by("id").first()
        if not self.config:
            self.config = HomepageConfiguration(code="availability-command-center")
        self.report = PowerBIReport.objects.filter(
            report_name__iexact=self.DATASET_NAME,
            is_active=True,
            validation_status="Validated",
        ).order_by("id").first()
        if not self.report:
            raise HomepageAvailabilityError(
                "Fuel Monitoring Report V1 is not configured and validated.",
                code="fuel_semantic_model_missing",
                status=503,
            )

    def request_from_params(self, params) -> HomepageRequest:
        period = str(params.get("period") or "ytd").strip().casefold()
        try:
            bounds(period)
        except ValueError as exc:
            raise HomepageAvailabilityError(str(exc), code="invalid_period", status=400) from None
        breakdown = str(params.get('breakdown') or 'overall').casefold()
        if breakdown not in {'overall','minesite','model','family','equipment'}:
            raise HomepageAvailabilityError('Unsupported grouping.',code='invalid_breakdown',status=400)
        if params.get('customer') or params.get('serial_number'):
            raise HomepageAvailabilityError('For Fuel, select a site, model, family or equipment identifier.',code='unsupported_fuel_filter',status=400)
        filters = {}
        for key in ("minesite", "model", "family", "equipment"):
            value = str(params.get(key) or "").strip()
            if value:
                filters[key] = _fuel_site(value) if key == "minesite" else value
        return HomepageRequest("fuel", period, breakdown, filters, 1, 200, "availability_desc", "")

    def _scope(self) -> tuple[dict, str, str]:
        try:
            platform_user = self.user.platformuser
        except (AttributeError, PlatformUser.DoesNotExist):
            platform_user = None
        if not platform_user or platform_user.is_platform_admin:
            return {}, "", ""
        raw_scope = platform_user.business_performance_scope or {}
        scope = {}
        if raw_scope.get("minesite"):
            values = raw_scope["minesite"] if isinstance(raw_scope["minesite"], list) else [raw_scope["minesite"]]
            scope["minesite"] = [_fuel_site(value) for value in values]
        role = str(raw_scope.get("rls_role") or "").strip()
        effective_user = str(platform_user.user_principal_name or platform_user.email or "").strip()
        return scope, role, effective_user

    @staticmethod
    def _merge_filters(scope: dict, requested: dict) -> dict:
        merged = {key: list(value) if isinstance(value, list) else [value] for key, value in scope.items()}
        for key, value in requested.items():
            if key in merged:
                allowed = {str(item).casefold() for item in merged[key]}
                if str(value).casefold() not in allowed:
                    raise HomepageAvailabilityError(
                        "You do not have access to the selected Fuel scope.",
                        code="scope_forbidden",
                        status=403,
                    )
            merged[key] = [value]
        return merged

    @classmethod
    def _filter_clauses(cls, filters: dict) -> list[str]:
        columns = {
            "minesite": cls.SITE_COLUMN,
            "model": cls.MODEL_COLUMN,
            "equipment": cls.EQUIPMENT_COLUMN,
            "family": cls.FAMILY_COLUMN,
        }
        clauses = []
        for code, values in filters.items():
            if code not in columns:
                continue
            items = values if isinstance(values, list) else [values]
            literals = ", ".join(_dax_string(item) for item in items if str(item).strip())
            if literals:
                clauses.append(f"TREATAS({{{literals}}}, {_dax_column(*columns[code])})")
        return clauses

    @staticmethod
    def _args(clauses: list[str]) -> str:
        return (",\n            " + ",\n            ".join(clauses)) if clauses else ""

    def build_dax(self, request: HomepageRequest, merged_filters: dict, scope: dict) -> str:
        date_column = _dax_column(*self.DATE_COLUMN)
        site_column = _dax_column(*self.SITE_COLUMN)
        model_column = _dax_column(*self.MODEL_COLUMN)
        equipment_column = _dax_column(*self.EQUIPMENT_COLUMN)
        clauses = self._filter_clauses(merged_filters)
        filter_args = self._args(clauses)
        benchmark_filters = dict(merged_filters)
        if "minesite" in request.filters:
            if scope.get("minesite"):
                benchmark_filters["minesite"] = scope["minesite"]
            else:
                benchmark_filters.pop("minesite", None)
        benchmark_args = self._args(self._filter_clauses(benchmark_filters))
        scope_args = self._args(self._filter_clauses(scope))
        if request.period == "ytd":
            start_expression = "DATE(YEAR(__LatestDate), 1, 1)"
            previous_start = "DATE(YEAR(__LatestDate) - 1, 1, 1)"
            previous_end = "EDATE(__LatestDate, -12)"
        else:
            start_expression = "EOMONTH(__LatestDate, -12) + 1"
            previous_start = "EOMONTH(__LatestDate, -24) + 1"
            previous_end = "EOMONTH(__LatestDate, -12)"
        custom_window = dax_window(request.period)
        end_expression = '__LatestDataDate'
        if custom_window:
            start_expression, end_expression, previous_start, previous_end = custom_window
        dimension_column = _dax_column(*{
            'minesite': self.SITE_COLUMN, 'model': self.MODEL_COLUMN,
            'family': self.FAMILY_COLUMN, 'equipment': self.EQUIPMENT_COLUMN,
            'overall': self.SITE_COLUMN,
        }[request.breakdown])
        return f"""
DEFINE
VAR __LatestDataDate =
    MAXX(
        FILTER(
            ALL({date_column}),
            NOT ISBLANK(CALCULATE({self.MEASURE}{filter_args}))
        ),
        {date_column}
    )
VAR __LatestDate = {end_expression}
VAR __StartDate = {start_expression}
VAR __PreviousStart = {previous_start}
VAR __PreviousEnd = {previous_end}
VAR __CurrentPeriod = DATESBETWEEN({date_column}, __StartDate, __LatestDate)
VAR __PreviousPeriod = DATESBETWEEN({date_column}, __PreviousStart, __PreviousEnd)
VAR __Summary =
    ROW(
        "RowType", "summary",
        "Entity", "Overall",
        "LPH", CALCULATE({self.MEASURE}, __CurrentPeriod{filter_args}),
        "PreviousLPH", CALCULATE({self.MEASURE}, __PreviousPeriod{filter_args}),
        "BenchmarkLPH", CALCULATE({self.MEASURE}, __CurrentPeriod{benchmark_args}),
        "EquipmentCount", CALCULATE(DISTINCTCOUNT({equipment_column}), __CurrentPeriod{filter_args}),
        "MineSiteCount", CALCULATE(DISTINCTCOUNT({site_column}), __CurrentPeriod{filter_args}),
        "LatestDate", __LatestDataDate,
        "Extra1", BLANK(),
        "Extra2", BLANK()
    )
VAR __EquipmentBase =
    SUMMARIZECOLUMNS(
        {equipment_column},
        __CurrentPeriod{filter_args},
        "LPH", {self.MEASURE},
        "Model", SELECTEDVALUE({model_column}),
        "MineSite", SELECTEDVALUE({site_column})
    )
VAR __Equipment =
    SELECTCOLUMNS(
        FILTER(__EquipmentBase, NOT ISBLANK([LPH]) && [LPH] >= 0),
        "RowType", "equipment",
        "Entity", {equipment_column},
        "LPH", [LPH],
        "PreviousLPH", BLANK(),
        "BenchmarkLPH", BLANK(),
        "EquipmentCount", BLANK(),
        "MineSiteCount", BLANK(),
        "LatestDate", BLANK(),
        "Extra1", [Model],
        "Extra2", [MineSite]
    )
VAR __MineSiteOptions =
    SELECTCOLUMNS(
        SUMMARIZECOLUMNS({site_column}, __CurrentPeriod{scope_args}, "OptionLPH", {self.MEASURE}),
        "RowType", "option_minesite",
        "Entity", {site_column},
        "LPH", BLANK(), "PreviousLPH", BLANK(), "BenchmarkLPH", BLANK(),
        "EquipmentCount", BLANK(), "MineSiteCount", BLANK(), "LatestDate", BLANK(),
        "Extra1", BLANK(), "Extra2", BLANK()
    )
VAR __ModelOptions =
    SELECTCOLUMNS(
        FILTER(SUMMARIZECOLUMNS({model_column}, __CurrentPeriod{filter_args}, "OptionLPH", {self.MEASURE}), NOT ISBLANK([OptionLPH])),
        "RowType", "option_model",
        "Entity", {model_column},
        "LPH", BLANK(), "PreviousLPH", BLANK(), "BenchmarkLPH", BLANK(),
        "EquipmentCount", BLANK(), "MineSiteCount", BLANK(), "LatestDate", BLANK(),
        "Extra1", BLANK(), "Extra2", BLANK()
    )
VAR __EquipmentOptions =
    SELECTCOLUMNS(
        FILTER(SUMMARIZECOLUMNS({equipment_column}, __CurrentPeriod{filter_args}, "OptionLPH", {self.MEASURE}), NOT ISBLANK([OptionLPH])),
        "RowType", "option_equipment",
        "Entity", {equipment_column},
        "LPH", BLANK(), "PreviousLPH", BLANK(), "BenchmarkLPH", BLANK(),
        "EquipmentCount", BLANK(), "MineSiteCount", BLANK(), "LatestDate", BLANK(),
        "Extra1", BLANK(), "Extra2", BLANK()
    )
VAR __Breakdown =
    SELECTCOLUMNS(
        FILTER(
            SUMMARIZECOLUMNS({dimension_column}, __CurrentPeriod{filter_args},
                "GroupLPH", {self.MEASURE},
                "GroupCount", DISTINCTCOUNT({equipment_column})),
            NOT ISBLANK([GroupLPH])
        ),
        "RowType", "breakdown", "Entity", {dimension_column}, "LPH", [GroupLPH],
        "PreviousLPH", BLANK(), "BenchmarkLPH", BLANK(),
        "EquipmentCount", [GroupCount], "MineSiteCount", BLANK(), "LatestDate", BLANK(),
        "Extra1", BLANK(), "Extra2", BLANK()
    )
VAR __Months =
    SELECTCOLUMNS(GENERATESERIES(0, MAX(0, DATEDIFF(__StartDate, __LatestDate, MONTH))),
        "MonthStart", EDATE(DATE(YEAR(__StartDate), MONTH(__StartDate), 1), [Value]))
VAR __Trend =
    SELECTCOLUMNS(__Months,
        "RowType", "trend", "Entity", FORMAT([MonthStart], "yyyy-MM"),
        "LPH", VAR __Month = [MonthStart]
            RETURN CALCULATE({self.MEASURE},
                DATESBETWEEN({date_column}, MAX(__StartDate, __Month), MIN(__LatestDate, EOMONTH(__Month, 0))){filter_args}),
        "PreviousLPH", BLANK(), "BenchmarkLPH", BLANK(),
        "EquipmentCount", BLANK(), "MineSiteCount", BLANK(), "LatestDate", BLANK(),
        "Extra1", BLANK(), "Extra2", BLANK()
    )
EVALUATE
UNION(__Summary, __Equipment, __MineSiteOptions, __ModelOptions, __EquipmentOptions, __Breakdown, __Trend)
""".strip()

    def _execute(self, dax: str, filters: dict, role: str, effective_user: str) -> list[dict]:
        payload = {
            "datasetId": self.report.semantic_model_id,
            "datasetName": self.DATASET_NAME,
            "query": dax,
            "question": "Mining 360 Fuel Consumption Excellence Center",
            "section": "fuel_monitoring",
            "metric": "fuel_lph",
            "measure": self.MEASURE,
            "filters": filters,
            "rlsRole": role,
            "roles": [role] if role else [],
            "effectiveUser": effective_user,
        }
        try:
            return _extract_rows(execute_dax_via_flow(payload))
        except PowerAutomateTransientError as exc:
            raise HomepageAvailabilityError(
                "Fuel consumption data is temporarily unavailable.",
                code="fuel_temporarily_unavailable",
                status=503,
            ) from exc
        except Exception as exc:
            raise HomepageAvailabilityError(
                "Fuel consumption data could not be loaded.",
                code="fuel_execution_failed",
                status=503,
            ) from exc

    def _refresh_metadata(self) -> tuple[str, str]:
        try:
            return get_latest_refresh_cached(
                get_access_token(),
                self.report.workspace_id,
                self.report.semantic_model_id,
                cache_seconds=max(60, int(self.config.cache_duration_seconds or 300)),
            )
        except Exception:
            return "", "Unavailable"

    def _normalize(self, rows: list[dict], request: HomepageRequest, elapsed_ms: int) -> dict:
        summary = next((row for row in rows if str(_row_value(row, "RowType") or "").casefold() == "summary"), {})
        value = _as_float(_row_value(summary, "LPH"))
        previous = _as_float(_row_value(summary, "PreviousLPH"))
        benchmark = _as_float(_row_value(summary, "BenchmarkLPH"))
        latest_date = _date_value(_row_value(summary, "LatestDate"))
        equipment_rows = []
        breakdown_rows = []
        trend_rows = []
        options = {"minesite": [], "model": [], "equipment": []}
        for row in rows:
            row_type = str(_row_value(row, "RowType") or "").casefold()
            if row_type == "equipment":
                lph = _as_float(_row_value(row, "LPH"))
                if lph is not None and math.isfinite(lph) and lph >= 0:
                    equipment_rows.append({
                        "equipment": str(_row_value(row, "Entity") or "").strip(),
                        "lph": lph,
                        "model": str(_row_value(row, "Extra1") or "").strip(),
                        "minesite": str(_row_value(row, "Extra2") or "").strip(),
                    })
            elif row_type in {'breakdown','trend'}:
                lph=_as_float(_row_value(row,'LPH'))
                if lph is not None and math.isfinite(lph) and lph>=0:
                    label=str(_row_value(row,'Entity') or '')
                    item={'entity':label,'metric_value':lph,'raw_value':lph,'value':lph,'formatted_value':_format_lph(lph),
                          'equipment_count':_as_int(_row_value(row,'EquipmentCount'))}
                    if row_type=='trend':
                        item['period']=label
                        trend_rows.append(item)
                    else:
                        breakdown_rows.append(item)
            elif row_type.startswith("option_"):
                code = row_type.removeprefix("option_")
                label = str(_row_value(row, "Entity") or "").strip()
                if code in options and label and label not in options[code]:
                    options[code].append(label)
        for values in options.values():
            values.sort(key=str.casefold)
        values = [row["lph"] for row in equipment_rows]
        ranked_equipment = sorted(
            (row for row in equipment_rows if row["lph"] > 0),
            key=lambda row: row["lph"],
        )

        def decision_item(row: dict) -> dict:
            return {
                "entity": row["equipment"] or "Unidentified equipment",
                "model": row["model"] or None,
                "minesite": row["minesite"] or None,
                "raw_value": row["lph"],
                "formatted_value": _format_lph(row["lph"]),
            }

        lowest_observed = [decision_item(row) for row in ranked_equipment[:5]]
        highest_observed = [decision_item(row) for row in reversed(ranked_equipment[-5:])]
        very_high_count = sum(1 for row in ranked_equipment if row["lph"] > 120)
        low_count = sum(1 for row in ranked_equipment if row["lph"] < 40)
        if not ranked_equipment:
            takeaway = "No equipment-level Fuel rate is available for decision support in this context."
        elif very_high_count:
            takeaway = (
                f"{very_high_count} equipment record an average Fuel rate above 120 L/h. "
                "Review model, duty cycle and operating conditions before drawing an efficiency conclusion."
            )
        else:
            takeaway = (
                f"No equipment records an average Fuel rate above 120 L/h; {low_count} are below 40 L/h. "
                "Compare equipment within the same model and duty cycle before taking action."
            )
        bins = list(range(20, 181, 20))
        distribution = []
        for upper in bins:
            lower = upper - 20
            count = sum(1 for item in values if lower <= item < upper)
            if upper == bins[-1]:
                count += sum(1 for item in values if item >= upper)
            distribution.append({
                "lph": upper,
                "count": count,
                "percentage": round(count / len(values) * 100, 1) if values else 0.0,
            })
        delta = value - previous if value is not None and previous is not None else None
        delta_percent = delta / abs(previous) * 100 if delta is not None and previous not in (None, 0) else None
        refresh_display, refresh_status = self._refresh_metadata()
        refresh_dt = None
        try:
            refresh_dt = timezone.make_aware(
                datetime.strptime(refresh_display, "%Y-%m-%d %I:%M %p"),
                timezone.get_current_timezone(),
            )
        except (TypeError, ValueError):
            pass
        stale = bool(refresh_dt and timezone.now() - refresh_dt > timedelta(hours=max(1, int(self.config.freshness_threshold_hours or 24))))
        return {
            "ok": True,
            "context": {
                "metric_code": "fuel",
                "metric_label": "Average Fuel Rate",
                "period_code": request.period,
                "period_label": "Year to Date" if request.period == "ytd" else "Last 12 Months",
                "start_date": _period_start(latest_date, request.period).isoformat() if latest_date else None,
                "end_date": latest_date.isoformat() if latest_date else None,
                **period_context(request.period,latest_date,_period_start(latest_date,request.period)),
                "breakdown": request.breakdown,
                "filters": request.filters,
            },
            "metric": {
                "code": "fuel",
                "label": "Average Fuel Rate",
                "unit": "L/h",
                "raw_value": value,
                "formatted_value": _format_lph(value),
                "comparison": {
                    "label": "vs previous rolling 12 months" if request.period == "last_12_months" else "vs same period last year",
                    "previous_raw": previous,
                    "previous_formatted": _format_lph(previous),
                    "delta_value": round(delta, 1) if delta is not None else None,
                    "delta_formatted": f"{delta:+.1f} L/h" if delta is not None else None,
                    "delta_percent": round(delta_percent, 1) if delta_percent is not None else None,
                } if delta is not None else None,
                "benchmark_raw": benchmark,
                "benchmark_formatted": _format_lph(benchmark),
            },
            "distribution": distribution,
            "statistics": {
                "lowest": _percentile(values, 0),
                "p25": _percentile(values, 0.25),
                "median": _percentile(values, 0.5),
                "p75": _percentile(values, 0.75),
                "highest": _percentile(values, 1),
            },
            "summary": {
                "minesite_count": _as_int(_row_value(summary, "MineSiteCount")),
                "equipment_count": len(values) or _as_int(_row_value(summary, "EquipmentCount")),
            },
            "equipment": equipment_rows,
            "breakdown": breakdown_rows,
            "trend": sorted(trend_rows,key=lambda row:row['period']),
            "decision_support": {
                "lowest_observed": lowest_observed,
                "highest_observed": highest_observed,
                "very_high_count": very_high_count,
                "low_count": low_count,
                "takeaway": takeaway,
            },
            "filter_options": options,
            "data_quality": {
                "latest_available_date": latest_date.isoformat() if latest_date else None,
                "last_refresh_at": refresh_display or None,
                "refresh_status": refresh_status,
                "is_stale": stale,
            },
            "meta": {
                "cached": False,
                "duration_ms": elapsed_ms,
                "source": "Fuel Monitoring Report V1",
                "measure": self.MEASURE,
                "flow": "inspectData4",
            },
        }

    def get(self, request: HomepageRequest, *, force_refresh=False) -> dict:
        scope, role, effective_user = self._scope()
        merged = self._merge_filters(scope, request.filters)
        cache_payload = {
            "page": request.page, "page_size": request.page_size, "ordering": request.ordering,
            "breakdown": request.breakdown, "query": request.query,
            "user": getattr(self.user, "pk", None),
            "scope": scope,
            "role": role,
            "period": request.period,
            "filters": request.filters,
            "dataset": self.report.semantic_model_id,
        }
        key = "homepage:fuel:v3:" + hashlib.sha256(
            json.dumps(cache_payload, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        cached = None if force_refresh else cache.get(key)
        if cached is not None:
            payload = dict(cached)
            payload["meta"] = {**payload["meta"], "cached": True}
            return payload
        started = time.monotonic()
        rows = self._execute(self.build_dax(request, merged, scope), merged, role, effective_user)
        payload = self._normalize(rows, request, int((time.monotonic() - started) * 1000))
        cache.set(key, payload, max(30, int(self.config.cache_duration_seconds or 300)))
        return payload
