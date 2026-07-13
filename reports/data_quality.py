from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from statistics import median
import math
import re
import statistics
from typing import Iterable


@dataclass
class DataQualityContext:
    source_key: str
    source_name: str
    object_kind: str
    object_name: str
    columns: list[str]
    column_types: list[str]
    records: list[dict]
    preview_url: str = ""
    previous_summary: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    @property
    def row_count(self) -> int:
        return len(self.records)


@dataclass
class DataQualityResult:
    key: str
    name: str
    category: str
    status: str
    impacted_records: int
    error_percentage: float
    description: str
    execution_ms: int
    records: list[dict] = field(default_factory=list)
    affected_columns: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)


CHECK_REGISTRY: list[type["DataQualityCheck"]] = []


def register_check(cls):
    CHECK_REGISTRY.append(cls)
    return cls


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _safe_float(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except Exception:
        return None


def _safe_text(value) -> str:
    return "" if value is None else str(value).strip()


def _is_empty(value) -> bool:
    return value is None or _safe_text(value) == ""


def _looks_like_date(column: str, sample_value=None) -> bool:
    name = column.lower()
    if any(token in name for token in ("date", "time", "datetime", "timestamp", "month", "year")):
        return True
    if isinstance(sample_value, datetime):
        return True
    text = _safe_text(sample_value)
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}", text))


def _looks_like_number(column: str, sample_value=None) -> bool:
    name = column.lower()
    if any(token in name for token in ("count", "qty", "quantity", "payload", "fuel", "smu", "duration", "percent", "ratio", "availability", "cycles", "cycle")):
        return True
    if isinstance(sample_value, (int, float)) and not isinstance(sample_value, bool):
        return True
    return bool(re.match(r"^-?\d+(?:\.\d+)?$", _safe_text(sample_value)))


def _parse_datetime(value):
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    text = _safe_text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except Exception:
        pass
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y",
    ):
        try:
            parsed = datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
            return parsed
        except Exception:
            continue
    return None


def _status_from_rate(rate: float, severity: str = "warning") -> str:
    if rate <= 0:
        return "OK"
    if rate >= 10 or severity == "critical":
        return "Critical"
    return "Warning"


def _build_records(records: Iterable[dict], rule: str, affected_columns: list[str] | None = None, max_records: int = 1000):
    payload = []
    affected_columns = affected_columns or []
    for index, row in enumerate(records):
        if len(payload) >= max_records:
            break
        item = dict(row)
        item["__rule__"] = rule
        if affected_columns:
            item["__columns__"] = affected_columns
        item["__row_index__"] = index
        payload.append(item)
    return payload


def _candidate_columns(columns: list[str], keywords: Iterable[str]) -> list[str]:
    lowered = [column.lower() for column in columns]
    matches = []
    for column, lower in zip(columns, lowered):
        if any(keyword in lower for keyword in keywords):
            matches.append(column)
    return matches


def _first_existing(columns: list[str], keywords: Iterable[str]) -> str | None:
    matches = _candidate_columns(columns, keywords)
    return matches[0] if matches else None


def _column_values(records: list[dict], column: str) -> list:
    return [row.get(column) for row in records]


def _row_signature(row: dict, columns: list[str]) -> tuple:
    return tuple(_safe_text(row.get(column)) for column in columns)


def _top_profiles(records: list[dict], columns: list[str]) -> dict:
    profiles = {}
    for column in columns:
        counter = Counter(_safe_text(row.get(column)) for row in records if not _is_empty(row.get(column)))
        if not counter:
            continue
        total = sum(counter.values())
        profiles[column] = {
            "total": total,
            "top": [
                {"value": value, "count": count, "pct": round((count / total) * 100, 2)}
                for value, count in counter.most_common(5)
            ],
        }
    return profiles


class DataQualityCheck:
    key = ""
    name = ""
    category = ""
    description = ""

    def run(self, context: DataQualityContext) -> DataQualityResult:
        raise NotImplementedError

    def _result(
        self,
        context: DataQualityContext,
        impacted_records: list[dict],
        description: str,
        execution_ms: int,
        affected_columns: list[str] | None = None,
        details: dict | None = None,
        severity: str = "warning",
    ) -> DataQualityResult:
        total = max(context.row_count, 1)
        rate = (len(impacted_records) / total) * 100
        status = "OK" if not impacted_records else _status_from_rate(rate, severity)
        return DataQualityResult(
            key=self.key,
            name=self.name,
            category=self.category,
            status=status,
            impacted_records=len(impacted_records),
            error_percentage=round(rate, 2),
            description=description,
            execution_ms=execution_ms,
            records=impacted_records,
            affected_columns=affected_columns or [],
            details=details or {},
        )


@register_check
class CompletenessChecks(DataQualityCheck):
    key = "completeness"
    name = "Completeness Checks"
    category = "Data Quality"
    description = "Null, empty string and mandatory field completeness analysis."

    def run(self, context: DataQualityContext) -> DataQualityResult:
        started = now_utc()
        rows = context.records
        columns = context.columns
        impacted = []
        missing_by_column = Counter()

        required_candidates = set(_candidate_columns(columns, ("id", "date", "site", "model", "serial", "equipment", "component", "status")))

        for row in rows:
            row_missing = []
            for column in columns:
                if _is_empty(row.get(column)):
                    missing_by_column[column] += 1
                    row_missing.append(column)
            if row_missing:
                impacted.append({**row, "__rule__": "null_or_empty", "__columns__": row_missing})

        missing_summary = ", ".join(f"{col} ({count})" for col, count in missing_by_column.most_common(5))
        required_missing = [column for column in required_candidates if missing_by_column.get(column, 0) == len(rows) and rows]
        description = "Missing values and empty strings detected."
        if missing_summary:
            description += f" Top affected columns: {missing_summary}."
        if required_missing:
            description += f" Required columns fully missing: {', '.join(required_missing)}."
        summary = {
            "column_completeness": {
                column: round(100 - (missing_by_column.get(column, 0) / max(len(rows), 1)) * 100, 2)
                for column in columns
            },
            "required_missing": required_missing,
        }
        return self._result(context, impacted, description, int((now_utc() - started).total_seconds() * 1000), list(missing_by_column.keys()), summary)


@register_check
class DuplicateChecks(DataQualityCheck):
    key = "duplicates"
    name = "Duplicate Checks"
    category = "Data Quality"
    description = "Duplicates on full row, composite keys and repeated records."

    def run(self, context: DataQualityContext) -> DataQualityResult:
        started = now_utc()
        rows = context.records
        columns = context.columns
        impacted = []
        details = {"rules": []}

        signatures = Counter(_row_signature(row, columns) for row in rows)
        duplicate_signatures = {signature for signature, count in signatures.items() if count > 1}
        for row in rows:
            if _row_signature(row, columns) in duplicate_signatures:
                impacted.append({**row, "__rule__": "identical_row_duplicate", "__columns__": columns})

        key_candidates = [column for column in columns if any(token in column.lower() for token in ("id", "key", "code", "number", "serial"))]
        if key_candidates:
            signatures = Counter(_row_signature(row, key_candidates) for row in rows)
            duplicate_keys = {signature for signature, count in signatures.items() if count > 1}
            for row in rows:
                if _row_signature(row, key_candidates) in duplicate_keys:
                    impacted.append({**row, "__rule__": "composite_or_key_duplicate", "__columns__": key_candidates})
            details["rules"].append({"name": "key_candidates", "columns": key_candidates})

        description = "Duplicate records detected on full rows or likely business keys."
        return self._result(context, impacted, description, int((now_utc() - started).total_seconds() * 1000), key_candidates, details, severity="critical")


@register_check
class UniquenessChecks(DataQualityCheck):
    key = "uniqueness"
    name = "Uniqueness Checks"
    category = "Data Quality"
    description = "Columns expected to be unique are checked for duplicates."

    def run(self, context: DataQualityContext) -> DataQualityResult:
        started = now_utc()
        rows = context.records
        columns = context.columns
        candidates = [column for column in columns if any(token in column.lower() for token in ("id", "serial", "number", "code", "key"))]
        impacted = []
        failed_columns = []
        for column in candidates:
            counter = Counter(_safe_text(row.get(column)) for row in rows if not _is_empty(row.get(column)))
            duplicates = {value for value, count in counter.items() if count > 1}
            if duplicates:
                failed_columns.append(column)
                for row in rows:
                    if _safe_text(row.get(column)) in duplicates:
                        impacted.append({**row, "__rule__": f"non_unique_{column}", "__columns__": [column]})
        description = "Unique columns contain duplicate values." if impacted else "No uniqueness issue detected."
        return self._result(context, impacted, description, int((now_utc() - started).total_seconds() * 1000), failed_columns, {"candidates": candidates})


@register_check
class ReferentialIntegrity(DataQualityCheck):
    key = "referential_integrity"
    name = "Referential Integrity"
    category = "Data Quality"
    description = "Reference values are matched against configured lookup values."

    def run(self, context: DataQualityContext) -> DataQualityResult:
        started = now_utc()
        reference_sets = context.metadata.get("reference_sets") or {}
        rows = context.records
        impacted = []
        failed = []
        if not reference_sets:
            return self._result(context, [], "No reference mappings configured for this source.", 0, severity="warning")

        for column, allowed_values in reference_sets.items():
            allowed = { _safe_text(item).lower() for item in allowed_values or [] if _safe_text(item) }
            if not allowed or column not in context.columns:
                continue
            failed.append(column)
            for row in rows:
                value = _safe_text(row.get(column))
                if value and value.lower() not in allowed:
                    impacted.append({**row, "__rule__": f"invalid_reference_{column}", "__columns__": [column]})
        description = "Reference values not found in lookup list." if impacted else "No referential gap detected."
        return self._result(context, impacted, description, int((now_utc() - started).total_seconds() * 1000), failed, {"reference_columns": failed})


@register_check
class ValidValues(DataQualityCheck):
    key = "valid_values"
    name = "Valid Values"
    category = "Data Quality"
    description = "Values must belong to the expected enumerations."

    ENUMS = {
        "planned": {"planned", "unplanned"},
        "work": {"working", "down"},
        "status": {"active", "inactive", "failed", "ok", "warning"},
        "yesno": {"yes", "no", "y", "n", "true", "false"},
        "pmtype": {"planned", "repetitive", "corrective"},
    }

    def run(self, context: DataQualityContext) -> DataQualityResult:
        started = now_utc()
        rows = context.records
        impacted = []
        failed_columns = []
        for column in context.columns:
            lower = column.lower()
            allowed = None
            if any(token in lower for token in ("planned", "type", "work")):
                allowed = self.ENUMS["planned"] | self.ENUMS["work"] | self.ENUMS["pmtype"]
            elif any(token in lower for token in ("status", "state", "flag")):
                allowed = self.ENUMS["status"] | self.ENUMS["yesno"]
            elif any(token in lower for token in ("yes", "no", "active", "inactive")):
                allowed = self.ENUMS["yesno"] | self.ENUMS["status"]
            if not allowed:
                continue
            invalid_rows = [row for row in rows if _safe_text(row.get(column)).lower() not in allowed and not _is_empty(row.get(column))]
            if invalid_rows:
                failed_columns.append(column)
                impacted.extend([{**row, "__rule__": f"invalid_value_{column}", "__columns__": [column]} for row in invalid_rows])
        description = "Values are outside the allowed list." if impacted else "All values belong to the expected set."
        return self._result(context, impacted, description, int((now_utc() - started).total_seconds() * 1000), failed_columns)


@register_check
class DateChecks(DataQualityCheck):
    key = "date_checks"
    name = "Date Checks"
    category = "Data Quality"
    description = "Future dates, stale dates, reversed ranges and negative durations."

    def run(self, context: DataQualityContext) -> DataQualityResult:
        started = now_utc()
        rows = context.records
        columns = context.columns
        impacted = []
        date_columns = [column for column in columns if any(token in column.lower() for token in ("date", "time", "month", "year", "start", "end"))]
        today = now_utc()
        for row in rows:
            for column in date_columns:
                value = _parse_datetime(row.get(column))
                if value is None:
                    continue
                if value > today + timedelta(days=1):
                    impacted.append({**row, "__rule__": f"future_date_{column}", "__columns__": [column]})
                if value.year < 1900:
                    impacted.append({**row, "__rule__": f"too_old_date_{column}", "__columns__": [column]})

        start_col = _first_existing(columns, ("start",))
        end_col = _first_existing(columns, ("end",))
        duration_col = _first_existing(columns, ("duration", "hours", "mins", "minutes"))
        if start_col and end_col:
            for row in rows:
                start_value = _parse_datetime(row.get(start_col))
                end_value = _parse_datetime(row.get(end_col))
                if start_value and end_value and end_value < start_value:
                    impacted.append({**row, "__rule__": "end_before_start", "__columns__": [start_col, end_col]})
                if duration_col:
                    duration = _safe_float(row.get(duration_col))
                    if duration is not None and duration < 0:
                        impacted.append({**row, "__rule__": "negative_duration", "__columns__": [duration_col]})

        description = "Date values show future/too old/reversed range issues." if impacted else "No date issue detected."
        return self._result(context, impacted, description, int((now_utc() - started).total_seconds() * 1000), date_columns)


@register_check
class NumericRangeChecks(DataQualityCheck):
    key = "numeric_ranges"
    name = "Numeric Range Checks"
    category = "Data Quality"
    description = "Negative values, business limits, percentages and known range violations."

    def run(self, context: DataQualityContext) -> DataQualityResult:
        started = now_utc()
        rows = context.records
        impacted = []
        failed_columns = []
        for column in context.columns:
            sample = next((row.get(column) for row in rows if not _is_empty(row.get(column))), None)
            if not _looks_like_number(column, sample):
                continue
            lower = column.lower()
            invalid = []
            for row in rows:
                numeric = _safe_float(row.get(column))
                if numeric is None:
                    continue
                if any(token in lower for token in ("percent", "availability", "ratio")) and not (0 <= numeric <= 100):
                    invalid.append(row)
                elif any(token in lower for token in ("payload", "fuel", "smu", "count", "duration", "cycles")) and numeric < 0:
                    invalid.append(row)
                elif any(token in lower for token in ("payload",)) and numeric > 1000000:
                    invalid.append(row)
            if invalid:
                failed_columns.append(column)
                impacted.extend([{**row, "__rule__": f"numeric_range_{column}", "__columns__": [column]} for row in invalid])
        description = "Numeric values are out of business range." if impacted else "All numeric values are within range."
        return self._result(context, impacted, description, int((now_utc() - started).total_seconds() * 1000), failed_columns)


@register_check
class ConsistencyChecks(DataQualityCheck):
    key = "consistency"
    name = "Consistency Checks"
    category = "Data Quality"
    description = "Checks consistency across multiple columns."

    def run(self, context: DataQualityContext) -> DataQualityResult:
        started = now_utc()
        rows = context.records
        columns = context.columns
        impacted = []
        reporting_col = _first_existing(columns, ("reporting",))
        last_reporting_col = _first_existing(columns, ("last reporting date", "lastreportingdate", "last reporting"))
        active_col = _first_existing(columns, ("active", "status"))

        for row in rows:
            if reporting_col and last_reporting_col:
                reporting = _safe_text(row.get(reporting_col)).lower()
                last_reporting = row.get(last_reporting_col)
                if reporting in {"yes", "true", "1", "active"} and _is_empty(last_reporting):
                    impacted.append({**row, "__rule__": "reporting_yes_last_date_null", "__columns__": [reporting_col, last_reporting_col]})
            if active_col and reporting_col:
                active = _safe_text(row.get(active_col)).lower()
                reporting = _safe_text(row.get(reporting_col)).lower()
                if active in {"inactive", "false", "0"} and reporting in {"yes", "true", "1"}:
                    impacted.append({**row, "__rule__": "inactive_but_reporting", "__columns__": [active_col, reporting_col]})

        description = "Column combinations are inconsistent." if impacted else "No consistency issue detected."
        return self._result(context, impacted, description, int((now_utc() - started).total_seconds() * 1000), [c for c in [reporting_col, last_reporting_col, active_col] if c])


@register_check
class BusinessRules(DataQualityCheck):
    key = "business_rules"
    name = "Business Rules"
    category = "Data Quality"
    description = "Application and maintenance business rules."

    def run(self, context: DataQualityContext) -> DataQualityResult:
        started = now_utc()
        rows = context.records
        columns = context.columns
        impacted = []
        pm_col = _first_existing(columns, ("pm", "maintenance"))
        repetitive_col = _first_existing(columns, ("repetitive",))
        availability_col = _first_existing(columns, ("availability",))
        payload_col = _first_existing(columns, ("payload",))
        cycle_col = _first_existing(columns, ("cycle count", "cycle", "cycles"))
        downtime_col = _first_existing(columns, ("downtime", "down time"))
        component_col = _first_existing(columns, ("component",))

        for row in rows:
            if pm_col and repetitive_col:
                if _safe_text(row.get(pm_col)).lower() == "pm" and _safe_text(row.get(repetitive_col)).lower() in {"yes", "true", "1"}:
                    impacted.append({**row, "__rule__": "pm_repetitive", "__columns__": [pm_col, repetitive_col]})
            if availability_col:
                availability = _safe_float(row.get(availability_col))
                if availability is not None and not (0 <= availability <= 100):
                    impacted.append({**row, "__rule__": "availability_out_of_bounds", "__columns__": [availability_col]})
            if payload_col and cycle_col:
                payload = _safe_float(row.get(payload_col))
                cycle = _safe_float(row.get(cycle_col))
                if payload is not None and (cycle is None or cycle <= 0):
                    impacted.append({**row, "__rule__": "payload_without_cycle_count", "__columns__": [payload_col, cycle_col]})
            if downtime_col and component_col:
                if not _is_empty(row.get(downtime_col)) and _is_empty(row.get(component_col)):
                    impacted.append({**row, "__rule__": "downtime_without_component", "__columns__": [downtime_col, component_col]})

        description = "Business rules violated." if impacted else "No business rule issue detected."
        return self._result(context, impacted, description, int((now_utc() - started).total_seconds() * 1000), [c for c in [pm_col, repetitive_col, availability_col, payload_col, cycle_col, downtime_col, component_col] if c])


@register_check
class TimeGapChecks(DataQualityCheck):
    key = "time_gaps"
    name = "Time Gap Checks"
    category = "Data Quality"
    description = "Gaps, overly close events and missing reporting for long periods."

    def run(self, context: DataQualityContext) -> DataQualityResult:
        started = now_utc()
        rows = context.records
        columns = context.columns
        impacted = []
        datetime_cols = [column for column in columns if any(token in column.lower() for token in ("date", "time", "timestamp", "reporting"))]
        machine_col = _first_existing(columns, ("machine", "equip", "asset"))

        for column in datetime_cols:
            values = sorted([_parse_datetime(row.get(column)) for row in rows if _parse_datetime(row.get(column)) is not None])
            for left, right in zip(values, values[1:]):
                if right - left > timedelta(days=30):
                    impacted.append({"__rule__": f"gap_{column}", "__columns__": [column], "__gap_days__": (right - left).days})
                if timedelta(0) < right - left < timedelta(minutes=1):
                    impacted.append({"__rule__": f"too_close_{column}", "__columns__": [column], "__gap_seconds__": int((right - left).total_seconds())})

        if machine_col and datetime_cols:
            last_col = datetime_cols[0]
            newest = {}
            for row in rows:
                key = _safe_text(row.get(machine_col))
                dt = _parse_datetime(row.get(last_col))
                if key and dt:
                    newest[key] = max(newest.get(key, dt), dt)
            stale_cutoff = now_utc() - timedelta(hours=48)
            for machine, dt in newest.items():
                if dt < stale_cutoff:
                    impacted.append({"__rule__": "machine_not_reporting", "__columns__": [machine_col, last_col], machine_col: machine, last_col: dt.isoformat()})

        description = "Reporting gaps or stale machines were detected." if impacted else "No time gap issue detected."
        return self._result(context, impacted, description, int((now_utc() - started).total_seconds() * 1000), datetime_cols)


@register_check
class FreshnessChecks(DataQualityCheck):
    key = "freshness"
    name = "Freshness Checks"
    category = "Data Quality"
    description = "Latest reporting age and data latency analysis."

    def run(self, context: DataQualityContext) -> DataQualityResult:
        started = now_utc()
        rows = context.records
        columns = context.columns
        impacted = []
        date_cols = [column for column in columns if any(token in column.lower() for token in ("last", "updated", "date", "time", "report"))]
        newest = None
        latest_col = None
        for column in date_cols:
            for row in rows:
                dt = _parse_datetime(row.get(column))
                if dt and (newest is None or dt > newest):
                    newest = dt
                    latest_col = column
        if newest:
            age_hours = (now_utc() - newest).total_seconds() / 3600
            if age_hours > 24:
                impacted.append({latest_col: newest.isoformat(), "__rule__": "stale_data"})
        else:
            impacted.append({"__rule__": "missing_freshness_signal"})
        description = "Source is stale or missing freshness signal." if impacted else "Source freshness is OK."
        return self._result(context, impacted, description, int((now_utc() - started).total_seconds() * 1000), [latest_col] if latest_col else [])


@register_check
class OutlierDetection(DataQualityCheck):
    key = "outliers"
    name = "Outlier Detection"
    category = "Data Quality"
    description = "Statistical outlier detection on numeric measures."

    def run(self, context: DataQualityContext) -> DataQualityResult:
        started = now_utc()
        rows = context.records
        impacted = []
        numeric_columns = []
        for column in context.columns:
            values = [_safe_float(row.get(column)) for row in rows]
            values = [value for value in values if value is not None]
            if len(values) < 8:
                continue
            if not _looks_like_number(column, values[0]):
                continue
            q1, q3 = statistics.quantiles(values, n=4, method="inclusive")[0], statistics.quantiles(values, n=4, method="inclusive")[2]
            iqr = q3 - q1
            if iqr == 0:
                continue
            lower = q1 - 1.5 * iqr
            upper = q3 + 1.5 * iqr
            numeric_columns.append(column)
            for row in rows:
                value = _safe_float(row.get(column))
                if value is not None and (value < lower or value > upper):
                    impacted.append({**row, "__rule__": f"outlier_{column}", "__columns__": [column], "__bounds__": [lower, upper]})
        description = "Numeric outliers detected." if impacted else "No statistical outlier detected."
        return self._result(context, impacted, description, int((now_utc() - started).total_seconds() * 1000), numeric_columns)


@register_check
class DistributionChecks(DataQualityCheck):
    key = "distribution"
    name = "Distribution Checks"
    category = "Data Quality"
    description = "Current distributions compared to the previous execution baseline."

    def run(self, context: DataQualityContext) -> DataQualityResult:
        started = now_utc()
        previous = context.previous_summary.get("profiles") or {}
        current_profiles = _top_profiles(context.records, context.columns)
        impacted = []
        if not previous:
            return self._result(context, [], "No historical baseline is available for distribution comparison.", 0, severity="warning", details={"profiles": current_profiles})

        for column, profile in current_profiles.items():
            old_profile = previous.get(column)
            if not old_profile:
                continue
            old_top = (old_profile.get("top") or [{}])[0]
            new_top = (profile.get("top") or [{}])[0]
            old_pct = float(old_top.get("pct", 0) or 0)
            new_pct = float(new_top.get("pct", 0) or 0)
            if abs(new_pct - old_pct) >= 20:
                impacted.append({column: new_top.get("value"), "__rule__": f"distribution_shift_{column}", "__columns__": [column], "__delta_pct__": round(new_pct - old_pct, 2)})

        description = "Distribution shifted beyond threshold." if impacted else "Distribution remains within historical tolerance."
        return self._result(context, impacted, description, int((now_utc() - started).total_seconds() * 1000), list(current_profiles.keys()), {"profiles": current_profiles})


@register_check
class CrossDatasetValidation(DataQualityCheck):
    key = "cross_dataset"
    name = "Cross Dataset Validation"
    category = "Data Quality"
    description = "Cross-checks against configured external systems."

    def run(self, context: DataQualityContext) -> DataQualityResult:
        started = now_utc()
        mappings = context.metadata.get("cross_dataset_rules") or {}
        if not mappings:
            return self._result(context, [], "No cross-dataset rule configured for this object.", 0, severity="warning")
        impacted = []
        for column, rule in mappings.items():
            if column not in context.columns:
                continue
            allowed = { _safe_text(value).lower() for value in rule.get("allowed_values", []) if _safe_text(value) }
            for row in context.records:
                value = _safe_text(row.get(column))
                if value and allowed and value.lower() not in allowed:
                    impacted.append({**row, "__rule__": f"cross_dataset_{column}", "__columns__": [column], "__source__": rule.get("source", "")})
        description = "Cross dataset mismatch detected." if impacted else "Cross dataset validation passed."
        return self._result(context, impacted, description, int((now_utc() - started).total_seconds() * 1000), list(mappings.keys()))


@register_check
class FormatChecks(DataQualityCheck):
    key = "format"
    name = "Format Checks"
    category = "Data Quality"
    description = "Format rules for serials, emails, identifiers and codes."

    EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    SERIAL_RE = re.compile(r"^[A-Z0-9\-]{4,}$", re.I)
    SITE_RE = re.compile(r"^[A-Z0-9_\-]{2,}$", re.I)

    def run(self, context: DataQualityContext) -> DataQualityResult:
        started = now_utc()
        rows = context.records
        impacted = []
        failed_columns = []
        for column in context.columns:
            lower = column.lower()
            if "email" in lower:
                invalid = [row for row in rows if not _is_empty(row.get(column)) and not self.EMAIL_RE.match(_safe_text(row.get(column)))]
            elif "serial" in lower:
                invalid = [row for row in rows if not _is_empty(row.get(column)) and not self.SERIAL_RE.match(_safe_text(row.get(column)))]
            elif "site" in lower or "code" in lower or "id" in lower:
                invalid = [row for row in rows if not _is_empty(row.get(column)) and len(_safe_text(row.get(column))) < 2]
            else:
                invalid = []
            if invalid:
                failed_columns.append(column)
                impacted.extend([{**row, "__rule__": f"format_{column}", "__columns__": [column]} for row in invalid])
        description = "Format violations detected." if impacted else "No format issue detected."
        return self._result(context, impacted, description, int((now_utc() - started).total_seconds() * 1000), failed_columns)


@register_check
class SequenceChecks(DataQualityCheck):
    key = "sequence"
    name = "Sequence Checks"
    category = "Data Quality"
    description = "Sequence monotonicity for dates, SMU and counters."

    def run(self, context: DataQualityContext) -> DataQualityResult:
        started = now_utc()
        rows = context.records
        columns = context.columns
        impacted = []
        smu_col = _first_existing(columns, ("smu",))
        time_col = _first_existing(columns, ("date", "time"))
        counter_col = _first_existing(columns, ("counter", "count", "cycles"))

        def _check_monotonic(column, parser=lambda x: x):
            last = None
            for row in rows:
                value = parser(row.get(column))
                if value is None:
                    continue
                nonlocal impacted
                if last is not None and value < last:
                    impacted.append({**row, "__rule__": f"decreasing_sequence_{column}", "__columns__": [column]})
                last = value

        if smu_col:
            _check_monotonic(smu_col, _safe_float)
        if time_col:
            _check_monotonic(time_col, _parse_datetime)
        if counter_col:
            _check_monotonic(counter_col, _safe_float)

        description = "Sequence order violations detected." if impacted else "No sequence issue detected."
        return self._result(context, impacted, description, int((now_utc() - started).total_seconds() * 1000), [c for c in [smu_col, time_col, counter_col] if c])


@register_check
class ConnectivityChecks(DataQualityCheck):
    key = "connectivity"
    name = "Connectivity Checks"
    category = "Data Quality"
    description = "Reporting connectivity and communication presence."

    def run(self, context: DataQualityContext) -> DataQualityResult:
        started = now_utc()
        rows = context.records
        columns = context.columns
        impacted = []
        active_col = _first_existing(columns, ("active", "status"))
        reporting_col = _first_existing(columns, ("reporting",))
        gps_col = _first_existing(columns, ("lat", "lon", "gps"))
        last_comm_col = _first_existing(columns, ("last communication", "lastcomm", "last reporting", "last update"))
        for row in rows:
            active = _safe_text(row.get(active_col)).lower() if active_col else ""
            reporting = _safe_text(row.get(reporting_col)).lower() if reporting_col else ""
            if active in {"active", "yes", "true", "1"} and reporting in {"no", "false", "0"}:
                impacted.append({**row, "__rule__": "active_without_reporting", "__columns__": [c for c in [active_col, reporting_col] if c]})
            if gps_col and _is_empty(row.get(gps_col)) and active in {"active", "yes", "true", "1"}:
                impacted.append({**row, "__rule__": "active_without_gps", "__columns__": [gps_col]})
            if last_comm_col:
                dt = _parse_datetime(row.get(last_comm_col))
                if dt and dt < now_utc() - timedelta(hours=24):
                    impacted.append({**row, "__rule__": "stale_communication", "__columns__": [last_comm_col]})
        description = "Connectivity gaps found." if impacted else "No connectivity issue detected."
        return self._result(context, impacted, description, int((now_utc() - started).total_seconds() * 1000), [c for c in [active_col, reporting_col, gps_col, last_comm_col] if c])


@register_check
class GPSChecks(DataQualityCheck):
    key = "gps"
    name = "GPS Checks"
    category = "Data Quality"
    description = "Latitude/longitude range checks and zero coordinate detection."

    def run(self, context: DataQualityContext) -> DataQualityResult:
        started = now_utc()
        rows = context.records
        columns = context.columns
        impacted = []
        lat_col = _first_existing(columns, ("latitude", "lat"))
        lon_col = _first_existing(columns, ("longitude", "lon", "lng"))
        for row in rows:
            lat = _safe_float(row.get(lat_col)) if lat_col else None
            lon = _safe_float(row.get(lon_col)) if lon_col else None
            if lat_col and lon_col and lat is not None and lon is not None:
                if lat == 0 and lon == 0:
                    impacted.append({**row, "__rule__": "zero_coordinates", "__columns__": [lat_col, lon_col]})
                if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                    impacted.append({**row, "__rule__": "invalid_coordinates", "__columns__": [lat_col, lon_col]})
        description = "Invalid GPS coordinates detected." if impacted else "No GPS issue detected."
        return self._result(context, impacted, description, int((now_utc() - started).total_seconds() * 1000), [c for c in [lat_col, lon_col] if c])


@register_check
class PayloadChecks(DataQualityCheck):
    key = "payload"
    name = "Payload Checks"
    category = "Data Quality"
    description = "Payload versus nominal payload and dipper count consistency."

    def run(self, context: DataQualityContext) -> DataQualityResult:
        started = now_utc()
        rows = context.records
        columns = context.columns
        impacted = []
        payload_col = _first_existing(columns, ("payload",))
        nominal_col = _first_existing(columns, ("nominal payload", "nominal"))
        dipper_col = _first_existing(columns, ("dipper", "bucket count"))
        for row in rows:
            payload = _safe_float(row.get(payload_col)) if payload_col else None
            nominal = _safe_float(row.get(nominal_col)) if nominal_col else None
            dipper = _safe_float(row.get(dipper_col)) if dipper_col else None
            if payload_col and payload is None:
                impacted.append({**row, "__rule__": "payload_null", "__columns__": [payload_col]})
            if payload is not None and nominal is not None and payload > nominal:
                impacted.append({**row, "__rule__": "payload_above_nominal", "__columns__": [payload_col, nominal_col]})
            if payload is not None and payload < 0.1:
                impacted.append({**row, "__rule__": "payload_too_low", "__columns__": [payload_col]})
            if dipper_col and dipper is not None and dipper < 0:
                impacted.append({**row, "__rule__": "invalid_dipper_count", "__columns__": [dipper_col]})
        description = "Payload issues detected." if impacted else "No payload issue detected."
        return self._result(context, impacted, description, int((now_utc() - started).total_seconds() * 1000), [c for c in [payload_col, nominal_col, dipper_col] if c])


@register_check
class SMUChecks(DataQualityCheck):
    key = "smu"
    name = "SMU Checks"
    category = "Data Quality"
    description = "SMU monotonicity, negative values and abnormal acceleration."

    def run(self, context: DataQualityContext) -> DataQualityResult:
        started = now_utc()
        rows = context.records
        columns = context.columns
        impacted = []
        smu_col = _first_existing(columns, ("smu",))
        if not smu_col:
            return self._result(context, [], "No SMU column was found.", 0, severity="warning")

        values = []
        for row in rows:
            smu = _safe_float(row.get(smu_col))
            if smu is None:
                impacted.append({**row, "__rule__": "smu_missing", "__columns__": [smu_col]})
                continue
            if smu < 0:
                impacted.append({**row, "__rule__": "smu_negative", "__columns__": [smu_col]})
            values.append((row, smu))
        for (row_prev, prev), (row_next, nxt) in zip(values, values[1:]):
            if nxt < prev:
                impacted.append({**row_next, "__rule__": "smu_decreasing", "__columns__": [smu_col]})
            if nxt - prev > max(500, prev * 0.5 + 1):
                impacted.append({**row_next, "__rule__": "smu_fast_increase", "__columns__": [smu_col], "__delta__": round(nxt - prev, 2)})
        description = "SMU anomalies detected." if impacted else "No SMU issue detected."
        return self._result(context, impacted, description, int((now_utc() - started).total_seconds() * 1000), [smu_col])


@register_check
class DowntimeChecks(DataQualityCheck):
    key = "downtime"
    name = "Downtime Checks"
    category = "Data Quality"
    description = "End time before start time, missing component/failure/down type and duration mismatch."

    def run(self, context: DataQualityContext) -> DataQualityResult:
        started = now_utc()
        rows = context.records
        columns = context.columns
        impacted = []
        start_col = _first_existing(columns, ("start",))
        end_col = _first_existing(columns, ("end",))
        duration_col = _first_existing(columns, ("duration", "downtimehours", "downtime"))
        component_col = _first_existing(columns, ("component",))
        failure_col = _first_existing(columns, ("failure type", "failure"))
        down_col = _first_existing(columns, ("down type", "downtime type", "worktype"))
        for row in rows:
            start = _parse_datetime(row.get(start_col)) if start_col else None
            end = _parse_datetime(row.get(end_col)) if end_col else None
            duration = _safe_float(row.get(duration_col)) if duration_col else None
            if start and end and end < start:
                impacted.append({**row, "__rule__": "end_before_start", "__columns__": [c for c in [start_col, end_col] if c]})
            if duration is not None and duration < 0:
                impacted.append({**row, "__rule__": "negative_downtime", "__columns__": [duration_col]})
            if component_col and _is_empty(row.get(component_col)):
                impacted.append({**row, "__rule__": "component_missing", "__columns__": [component_col]})
            if failure_col and _is_empty(row.get(failure_col)):
                impacted.append({**row, "__rule__": "failure_type_missing", "__columns__": [failure_col]})
            if down_col and _is_empty(row.get(down_col)):
                impacted.append({**row, "__rule__": "down_type_missing", "__columns__": [down_col]})
        description = "Downtime rows contain date or classification gaps." if impacted else "No downtime issue detected."
        return self._result(context, impacted, description, int((now_utc() - started).total_seconds() * 1000), [c for c in [start_col, end_col, duration_col, component_col, failure_col, down_col] if c])


@register_check
class PerformanceChecks(DataQualityCheck):
    key = "performance"
    name = "Performance Checks"
    category = "Data Quality"
    description = "Row count, machine count, cycle count and payload variation compared to the latest baseline."

    def run(self, context: DataQualityContext) -> DataQualityResult:
        started = now_utc()
        previous = context.previous_summary or {}
        rows = context.records
        columns = context.columns
        impacted = []
        row_count = len(rows)
        machine_col = _first_existing(columns, ("machine", "equip", "asset"))
        cycle_col = _first_existing(columns, ("cycle",))
        payload_col = _first_existing(columns, ("payload",))
        machine_count = len({ _safe_text(row.get(machine_col)) for row in rows if machine_col and not _is_empty(row.get(machine_col)) }) if machine_col else 0
        cycle_count = sum(_safe_float(row.get(cycle_col)) or 0 for row in rows) if cycle_col else 0
        payload_avg = None
        if payload_col:
            payloads = [_safe_float(row.get(payload_col)) for row in rows]
            payloads = [value for value in payloads if value is not None]
            if payloads:
                payload_avg = round(sum(payloads) / len(payloads), 2)

        prev_row_count = previous.get("row_count")
        if prev_row_count:
            delta = abs(row_count - prev_row_count) / max(prev_row_count, 1) * 100
            if delta >= 20:
                impacted.append({"__rule__": "row_count_shift", "__delta_pct__": round(delta, 2)})
        prev_machine_count = previous.get("machine_count")
        if prev_machine_count and machine_count:
            delta = abs(machine_count - prev_machine_count) / max(prev_machine_count, 1) * 100
            if delta >= 20:
                impacted.append({"__rule__": "machine_count_shift", "__delta_pct__": round(delta, 2)})
        prev_cycle_count = previous.get("cycle_count")
        if prev_cycle_count and cycle_count:
            delta = abs(cycle_count - prev_cycle_count) / max(prev_cycle_count, 1) * 100
            if delta >= 20:
                impacted.append({"__rule__": "cycle_count_shift", "__delta_pct__": round(delta, 2)})
        prev_payload_avg = previous.get("payload_avg")
        if prev_payload_avg and payload_avg:
            delta = abs(payload_avg - prev_payload_avg) / max(prev_payload_avg, 1) * 100
            if delta >= 20:
                impacted.append({"__rule__": "payload_shift", "__delta_pct__": round(delta, 2)})

        description = "Performance metrics moved materially versus baseline." if impacted else "Performance metrics are stable."
        details = {
            "row_count": row_count,
            "machine_count": machine_count,
            "cycle_count": cycle_count,
            "payload_avg": payload_avg,
        }
        return self._result(context, impacted, description, int((now_utc() - started).total_seconds() * 1000), [c for c in [machine_col, cycle_col, payload_col] if c], details)


def available_checks() -> list[DataQualityCheck]:
    return [check() for check in CHECK_REGISTRY]


def build_context_summary(context: DataQualityContext) -> dict:
    columns = context.columns
    row_count = context.row_count
    machine_col = _first_existing(columns, ("machine", "equip", "asset"))
    cycle_col = _first_existing(columns, ("cycle",))
    payload_col = _first_existing(columns, ("payload",))
    machine_count = len({ _safe_text(row.get(machine_col)) for row in context.records if machine_col and not _is_empty(row.get(machine_col)) }) if machine_col else 0
    cycle_count = sum(_safe_float(row.get(cycle_col)) or 0 for row in context.records) if cycle_col else 0
    payload_values = [_safe_float(row.get(payload_col)) for row in context.records] if payload_col else []
    payload_values = [value for value in payload_values if value is not None]
    payload_avg = round(sum(payload_values) / len(payload_values), 2) if payload_values else None

    categorical_columns = []
    for column in columns:
        if _looks_like_number(column):
            continue
        values = [row.get(column) for row in context.records if not _is_empty(row.get(column))]
        if 0 < len(set(_safe_text(value) for value in values)) <= 20:
            categorical_columns.append(column)
    return {
        "row_count": row_count,
        "machine_count": machine_count,
        "cycle_count": cycle_count,
        "payload_avg": payload_avg,
        "profiles": _top_profiles(context.records, categorical_columns[:8]),
        "generated_at": now_utc().isoformat(),
    }


def compute_score(results: list[DataQualityResult]) -> float:
    if not results:
        return 100.0
    score = 100.0
    for result in results:
        weight = 1.0 if result.status == "Critical" else 0.5 if result.status == "Warning" else 0.0
        score -= min(result.error_percentage * weight, 15)
    return round(max(score, 0.0), 2)


def serialize_result(result: DataQualityResult) -> dict:
    return {
        "key": result.key,
        "name": result.name,
        "category": result.category,
        "status": result.status,
        "impacted_records": result.impacted_records,
        "error_percentage": result.error_percentage,
        "description": result.description,
        "execution_ms": result.execution_ms,
        "records": result.records,
        "affected_columns": result.affected_columns,
        "details": result.details,
    }


def run_checks(context: DataQualityContext, control_keys: list[str] | None = None) -> list[DataQualityResult]:
    controls = available_checks()
    if control_keys:
        key_set = {key.lower() for key in control_keys}
        controls = [control for control in controls if control.key.lower() in key_set]
    previous = context.previous_summary or {}
    results = []
    for control in controls:
        result = control.run(context)
        results.append(result)
    return results
