from __future__ import annotations

import hashlib
import json
import statistics
import time
from dataclasses import dataclass
from typing import Iterable

from django.core.cache import cache
from django.utils import timezone

from .models import BusinessPerformanceConfig, BusinessPerformanceMapping, BusinessPerformanceQueryLog
from .power_automate import execute_dax_via_flow
from .powerbi import execute_dataset_dax, resolve_workspace_dataset_id


class BusinessPerformanceError(RuntimeError):
    pass


class MappingNotConfigured(BusinessPerformanceError):
    pass


def _quote_identifier(value: str) -> str:
    return value.replace("'", "''").replace("]", "]]" )


def _dax_string(value) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def _extract_rows(payload: dict) -> list[dict]:
    rows = payload.get("firstTableRows")
    if isinstance(rows, list):
        return rows
    try:
        return payload["results"][0]["tables"][0]["rows"]
    except (KeyError, IndexError, TypeError):
        return []


def _clean_row(row: dict) -> dict:
    cleaned = {}
    for key, value in row.items():
        label = str(key).strip("[]")
        if "][" in label:
            label = label.rsplit("][", 1)[-1].strip("[]")
        cleaned[label] = value
    return cleaned


@dataclass
class QueryResult:
    rows: list[dict]
    dax: str
    cached: bool = False


class BusinessPerformanceService:
    KPI_LOGICAL_NAMES = (
        "parts_revenue", "prime_revenue", "total_revenue", "top3_contribution",
        "active_customers",
    )
    CUSTOMER_METRICS = (
        "parts_revenue", "parts_contribution", "prime_revenue", "total_revenue",
    )
    FILTER_KEYS = (
        "year", "period", "lob", "division", "company", "branch", "country",
        "customer", "minesite", "equipment_type", "model", "fleet_status",
        "customer_category", "distribution_channel",
    )

    def __init__(self, user=None):
        self.user = user
        self.config = BusinessPerformanceConfig.objects.filter(is_active=True).first()
        if not self.config:
            raise BusinessPerformanceError("Business Performance configuration is missing.")
        self.mappings = {
            item.logical_name: item
            for item in BusinessPerformanceMapping.objects.filter(is_active=True)
        }

    def mapping(self, logical_name: str, required: bool = True) -> BusinessPerformanceMapping | None:
        item = self.mappings.get(logical_name)
        if required and (not item or not item.object_name or (item.object_type == "column" and not item.table_name)):
            raise MappingNotConfigured(f"The mapping '{logical_name}' is not configured.")
        return item

    def object_ref(self, logical_name: str) -> str:
        item = self.mapping(logical_name)
        if item.object_type == "measure":
            return f"[{_quote_identifier(item.object_name)}]"
        return f"'{_quote_identifier(item.table_name)}'[{_quote_identifier(item.object_name)}]"

    def _scope_filters(self) -> dict:
        platform_user = getattr(self.user, "platformuser", None)
        if not platform_user or platform_user.is_platform_admin:
            return {}
        scope = platform_user.business_performance_scope or {}
        return {key: value for key, value in scope.items() if key in self.FILTER_KEYS and value}

    def _rls_role(self) -> str:
        platform_user = getattr(self.user, "platformuser", None)
        if not platform_user or platform_user.is_platform_admin:
            return ""
        return str((platform_user.business_performance_scope or {}).get("rls_role") or "").strip()

    def normalized_filters(self, filters: dict | None) -> dict:
        values = {}
        values.update(self._scope_filters())
        for key, raw in (filters or {}).items():
            if key not in self.FILTER_KEYS or raw in (None, "", []):
                continue
            values[key] = raw if isinstance(raw, list) else [raw]
        return values

    def filter_expressions(self, filters: dict | None) -> list[str]:
        expressions = []
        for key, values in self.normalized_filters(filters).items():
            mapping = self.mapping(key, required=False)
            if not mapping or not mapping.table_name or not mapping.object_name:
                continue
            values = values if isinstance(values, list) else [values]
            serialized = ", ".join(_dax_string(value) for value in values)
            expressions.append(f"TREATAS({{{serialized}}}, {self.object_ref(key)})")
        return expressions

    def _dataset_id(self) -> str:
        if self.config.semantic_model_id:
            return self.config.semantic_model_id
        return resolve_workspace_dataset_id(self.config.semantic_model_name)

    @staticmethod
    def _is_transient_connection_error(exc: Exception) -> bool:
        text = str(exc).lower()
        markers = (
            "connection aborted", "connection reset", "forcibly closed",
            "10054", "remote host", "temporarily unavailable", "timed out",
            "timeout", "max retries exceeded",
        )
        return any(marker in text for marker in markers)

    def _execute_remote_query(self, dataset_id: str, dax: str, action: str, filters: dict | None) -> list[dict]:
        rls_role = self._rls_role()
        attempts = 3
        last_error = None
        for attempt in range(1, attempts + 1):
            try:
                if rls_role:
                    result = execute_dax_via_flow({
                        "datasetId": dataset_id,
                        "datasetName": self.config.semantic_model_name,
                        "query": dax,
                        "question": f"Business Performance: {action}",
                        "section": "business_performance",
                        "filters": self.normalized_filters(filters),
                        "rlsRole": rls_role,
                        "roles": [rls_role],
                        "effectiveUser": getattr(self.user, "email", "") or getattr(self.user, "username", ""),
                    })
                    return _extract_rows(result)
                return execute_dataset_dax(dataset_id, dax)
            except Exception as exc:
                last_error = exc
                if attempt >= attempts or not self._is_transient_connection_error(exc):
                    raise
                time.sleep(attempt)
        raise last_error

    def execute(self, dax: str, page: str, action: str, filters: dict | None = None, use_cache: bool = True) -> QueryResult:
        dataset_id = self._dataset_id()
        cache_key = "bp:" + hashlib.sha256(f"{dataset_id}|{dax}".encode("utf-8")).hexdigest()
        if use_cache:
            cached_rows = cache.get(cache_key)
            if cached_rows is not None:
                return QueryResult(cached_rows, dax, True)
        started = time.monotonic()
        try:
            raw_rows = self._execute_remote_query(dataset_id, dax, action, filters)
            rows = [_clean_row(row) for row in raw_rows]
            duration = int((time.monotonic() - started) * 1000)
            cache.set(cache_key, rows, self.config.cache_duration_seconds)
            self.config.last_successful_refresh = timezone.now()
            self.config.save(update_fields=["last_successful_refresh", "updated_at"])
            BusinessPerformanceQueryLog.objects.create(
                user=self.user if getattr(self.user, "is_authenticated", False) else None,
                page=page, action=action, filters=self.normalized_filters(filters), dax_query=dax,
                duration_ms=duration, status="Completed", row_count=len(rows),
            )
            return QueryResult(rows, dax)
        except Exception as exc:
            BusinessPerformanceQueryLog.objects.create(
                user=self.user if getattr(self.user, "is_authenticated", False) else None,
                page=page, action=action, filters=self.normalized_filters(filters), dax_query=dax,
                duration_ms=int((time.monotonic() - started) * 1000), status="Failed",
                error_message=str(exc)[:4000],
            )
            raise BusinessPerformanceError(str(exc)) from exc

    def _summarize(self, dimensions: Iterable[str], metrics: Iterable[str], filters: dict | None, top_n: int | None = None, order_metric: str | None = None) -> str:
        dimension_refs = [self.object_ref(item) for item in dimensions]
        filter_refs = self.filter_expressions(filters)
        values = []
        for logical_name in metrics:
            mapping = self.mapping(logical_name, required=False)
            if mapping and mapping.object_name:
                values.extend([_dax_string(mapping.display_name), self.object_ref(logical_name)])
        if not values:
            raise MappingNotConfigured("No configured measure is available for this query.")
        body = ",\n    ".join(dimension_refs + filter_refs + values)
        query = f"SUMMARIZECOLUMNS(\n    {body}\n)"
        if top_n:
            order = self.object_ref(order_metric or "parts_revenue")
            query = f"TOPN({int(top_n)}, {query}, {order}, DESC)"
        return "EVALUATE\n" + query

    def overview(self, filters: dict | None = None, top_n: int | None = None) -> dict:
        top_n = max(1, min(int(top_n or self.config.top_n_default), 500))
        metrics = [name for name in self.KPI_LOGICAL_NAMES if self.mapping(name, False) and self.mapping(name, False).object_name]
        overview_dax = self._summarize([], metrics, filters)
        top_dax = self._summarize(["customer"], self.CUSTOMER_METRICS, filters, top_n, "parts_revenue")
        trend_dax = self._summarize(["year"], ["parts_revenue", "prime_revenue", "total_revenue"], filters)
        overview = self.execute(overview_dax, "Overview", "Executive overview", filters)
        top = self.execute(top_dax, "Overview", "Top customers", filters)
        trend = self.execute(trend_dax, "Overview", "Revenue trend", filters)
        customers = top.rows
        insights = self._insights(customers)
        return {
            "kpis": overview.rows[0] if overview.rows else {},
            "customers": customers,
            "trend": trend.rows,
            "pareto": self._pareto(customers),
            "insights": insights,
            "last_refresh": self.config.last_successful_refresh,
            "cached": overview.cached and top.cached and trend.cached,
        }

    def customers(self, filters: dict | None = None, limit: int = 500) -> list[dict]:
        dax = self._summarize(["customer"], self.CUSTOMER_METRICS, filters, min(limit, 2000), "total_revenue")
        return self.execute(dax, "Customers", "Customer list", filters).rows

    def filter_options(self, logical_name: str, filters: dict | None = None, limit: int = 500) -> list:
        mapping = self.mapping(logical_name)
        if mapping.object_type != "column":
            raise MappingNotConfigured(f"'{logical_name}' is not a filter column.")
        dax = self._summarize([logical_name], ["active_fleet"], filters, min(limit, 1000), "active_fleet")
        rows = self.execute(dax, "Filters", f"Options for {logical_name}", filters).rows
        return [row.get(mapping.display_name) for row in rows if row.get(mapping.display_name) not in (None, "")]

    def customer_details(self, customer: str, filters: dict | None = None) -> dict:
        merged = dict(filters or {})
        merged["customer"] = customer
        return {
            "customer": customer,
            "summary": self.overview(merged, 20),
            "parts": self.detail_rows("parts", merged, 200),
            "prime": self.detail_rows("prime", merged, 200),
        }

    def detail_rows(self, category: str, filters: dict | None = None, limit: int = 1000) -> list[dict]:
        filters = dict(filters or {})
        if category == "fleet" and not filters.get("fleet_status"):
            self.mapping("fleet_status")
            filters["fleet_status"] = self.config.active_fleet_status_value
        dimensions = [
            item.logical_name for item in self.mappings.values()
            if item.is_visible and item.object_type == "column" and item.table_name
            and (item.category == category or item.logical_name in {"customer", "year", "period"})
        ]
        metrics = {
            "parts": ["parts_revenue"],
            "prime": ["prime_revenue", "machine_count"],
        }.get(category, [])
        dax = self._summarize(dimensions, metrics, filters, min(max(int(limit), 1), 10000), metrics[0])
        return self.execute(dax, category.title(), f"{category} details", filters).rows

    @staticmethod
    def _number(row: dict, label: str) -> float:
        try:
            return float(row.get(label) or 0)
        except (TypeError, ValueError):
            return 0.0

    def _pareto(self, rows: list[dict]) -> list[dict]:
        revenue_label = self.mapping("parts_revenue").display_name
        customer_label = self.mapping("customer").display_name
        ordered = sorted(rows, key=lambda row: self._number(row, revenue_label), reverse=True)
        total = sum(self._number(row, revenue_label) for row in ordered)
        cumulative = 0.0
        result = []
        for row in ordered:
            value = self._number(row, revenue_label)
            cumulative += value
            result.append({"customer": row.get(customer_label), "value": value, "cumulative_pct": cumulative / total if total else 0})
        return result

    def _opportunity(self, rows: list[dict]) -> dict:
        fleet_label = self.mapping("active_fleet").display_name
        revenue_label = self.mapping("parts_revenue_per_fleet").display_name
        fleets = [self._number(row, fleet_label) for row in rows]
        revenues = [self._number(row, revenue_label) for row in rows]
        aggregate = statistics.mean if self.config.opportunity_threshold_mode == "average" else statistics.median
        fleet_threshold = float(self.config.opportunity_fleet_threshold) if self.config.opportunity_fleet_threshold is not None else (aggregate(fleets) if fleets else 0)
        revenue_threshold = float(self.config.opportunity_revenue_threshold) if self.config.opportunity_revenue_threshold is not None else (aggregate(revenues) if revenues else 0)
        return {"rows": rows, "fleet_threshold": fleet_threshold, "revenue_threshold": revenue_threshold}

    def _insights(self, rows: list[dict]) -> list[str]:
        if not rows:
            return []
        customer_label = self.mapping("customer").display_name
        parts_label = self.mapping("parts_revenue").display_name
        by_parts = max(rows, key=lambda row: self._number(row, parts_label))
        prime_label = self.mapping("prime_revenue").display_name
        by_prime = max(rows, key=lambda row: self._number(row, prime_label))
        total = sum(self._number(row, parts_label) for row in rows)
        top3 = sum(self._number(row, parts_label) for row in sorted(rows, key=lambda row: self._number(row, parts_label), reverse=True)[:3])
        return [
            f"The Top 3 customers account for {(top3 / total * 100 if total else 0):.1f}% of Parts Revenue.",
            f"{by_parts.get(customer_label, 'The leading customer')} generates the highest Parts Revenue.",
            f"{by_prime.get(customer_label, 'The leading customer')} generates the highest Prime Revenue.",
            "Parts and Prime revenue concentration should be reviewed together when prioritizing strategic accounts.",
        ]
