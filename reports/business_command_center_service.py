from __future__ import annotations

import copy
import hashlib
import json
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.core.cache import cache
from django.db.models import Max, Q, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from .business_mapping_access_service import authorized_account_codes
from .business_mapping_source_service import MINING_DIVISION, MINING_REVENUE_LOBS, UNCLASSIFIED_REVENUE_LOB
from .business_review_access_service import filter_published_rows
from .models import (
    BusinessCommandCenterUserVisit,
    BusinessCommandCenterWatchlist,
    BusinessReviewAction,
    BusinessReviewSnapshot,
    MappingPublication,
    RevenueSourceSnapshot,
)


BUSINESS_LINES = {
    "machine": ("PRIME", "Machine"),
    "parts": ("PARTS", "Parts"),
    "service": ("SERVICE", "Service"),
    "rental": ("RENTAL", "Rental"),
    "unclassified": (UNCLASSIFIED_REVENUE_LOB, "Unclassified"),
}
ALL_LOBS = tuple(value[0] for value in BUSINESS_LINES.values())


class BusinessCommandCenterInputError(ValueError):
    pass


def _amount(queryset):
    return queryset.aggregate(value=Sum("revenue_eur"))["value"] or Decimal("0")


def _float(value):
    return float(value) if value is not None else None


def _shift_year(value, years=-1):
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(year=value.year + years, day=28)


class BusinessRevenuePeriodService:
    PERIODS = {"ytd", "last_year", "current_month", "custom"}
    COMPARISONS = {"same_period_last_year", "previous_equivalent_period", "none"}

    @classmethod
    def resolve(cls, latest_date, period="ytd", start_date=None, end_date=None, comparison="same_period_last_year"):
        if not latest_date:
            raise BusinessCommandCenterInputError("Revenue business dates are not available in the current snapshot.")
        period = str(period or "ytd").strip().lower()
        comparison = str(comparison or "same_period_last_year").strip().lower()
        if period not in cls.PERIODS:
            raise BusinessCommandCenterInputError("The selected Revenue period is not supported.")
        if comparison not in cls.COMPARISONS:
            raise BusinessCommandCenterInputError("The selected comparison period is not supported.")
        if period == "ytd":
            start, end = date(latest_date.year, 1, 1), latest_date
            label = f"YTD {latest_date.year}"
        elif period == "last_year":
            start, end = date(latest_date.year - 1, 1, 1), date(latest_date.year - 1, 12, 31)
            label = str(latest_date.year - 1)
        elif period == "current_month":
            start, end = latest_date.replace(day=1), latest_date
            label = latest_date.strftime("%B %Y")
        else:
            try:
                start = date.fromisoformat(str(start_date or ""))
                end = date.fromisoformat(str(end_date or ""))
            except ValueError as exc:
                raise BusinessCommandCenterInputError("A valid Start Date and End Date are required.") from exc
            if start > end:
                raise BusinessCommandCenterInputError("Start Date must be before or equal to End Date.")
            if end > latest_date:
                raise BusinessCommandCenterInputError("The selected range extends beyond the latest available Revenue date.")
            if (end - start).days > 1461:
                raise BusinessCommandCenterInputError("The selected range exceeds the four-year retained Revenue window.")
            label = f"{start:%d %b %Y} - {end:%d %b %Y}"

        if comparison == "none":
            comparison_start = comparison_end = None
            comparison_label = "No comparison"
        elif comparison == "previous_equivalent_period":
            days = (end - start).days + 1
            comparison_end = start - timedelta(days=1)
            comparison_start = comparison_end - timedelta(days=days - 1)
            comparison_label = f"Previous {days}-day period"
        elif period == "last_year":
            comparison_start, comparison_end = date(start.year - 1, 1, 1), date(end.year - 1, 12, 31)
            comparison_label = str(start.year - 1)
        else:
            comparison_start, comparison_end = _shift_year(start), _shift_year(end)
            comparison_label = f"Same period {comparison_start.year}"
        return {
            "code": period, "label": label, "start_date": start, "end_date": end,
            "comparison": comparison, "comparison_label": comparison_label,
            "comparison_start_date": comparison_start, "comparison_end_date": comparison_end,
        }


class BusinessCommandCenterService:
    RULE_VERSION = "1.0"
    CACHE_SECONDS = 300

    def __init__(self, user, params=None):
        self.user = user
        self.params = params or {}

    def _csv(self, key):
        raw = self.params.get(key, "")
        values = raw if isinstance(raw, list) else str(raw).split(",")
        return {str(value).strip() for value in values if str(value).strip()}

    def _context(self):
        revenue = RevenueSourceSnapshot.objects.filter(active=True, division__iexact=MINING_DIVISION)
        account_scope = authorized_account_codes(self.user)
        if account_scope is not None:
            scope_filter = Q()
            for code in account_scope:
                scope_filter |= Q(source_account_code__iexact=code)
            revenue = revenue.filter(scope_filter) if account_scope else revenue.none()
        latest_date = revenue.aggregate(value=Max("business_date"))["value"]
        period = BusinessRevenuePeriodService.resolve(
            latest_date,
            self.params.get("period", "ytd"), self.params.get("start_date"), self.params.get("end_date"),
            self.params.get("comparison", "same_period_last_year"),
        )
        source_row = revenue.select_related("synchronization_run").order_by("-source_last_seen_at").first()
        if not source_row:
            raise BusinessCommandCenterInputError("No governed Revenue snapshot is available.")
        publication = MappingPublication.objects.filter(status="Published").order_by("-version").first()
        snapshot = publication.snapshot_json or {} if publication else {}
        classification_rows = snapshot.get("accounts") or snapshot.get("mappings", [])
        published_rows = filter_published_rows(list(classification_rows), self.user) if publication else []
        customers, countries, key_accounts = self._csv("customer_ids"), self._csv("country_ids"), self._csv("key_account_ids")
        selected_rows = published_rows
        if customers:
            selected_rows = [row for row in selected_rows if row.get("account_id") in customers]
        if countries:
            selected_rows = [row for row in selected_rows if row.get("business_country") in countries]
        if key_accounts:
            selected_rows = [row for row in selected_rows if row.get("key_account_id") in key_accounts]
        if customers or countries or key_accounts:
            selected_codes = {str(code) for row in selected_rows for code in row.get("source_account_codes", []) if code}
            revenue = revenue.filter(source_account_code__in=selected_codes) if selected_codes else revenue.none()
        business_line = str(self.params.get("business_line") or "all_business").strip().lower()
        if business_line not in {"all_business", *BUSINESS_LINES}:
            raise BusinessCommandCenterInputError("The selected Business Line is not supported.")
        return revenue, publication, published_rows, selected_rows, period, business_line, source_row.synchronization_run

    @staticmethod
    def _range(queryset, start, end):
        if not start or not end:
            return queryset.none()
        return queryset.filter(business_date__gte=start, business_date__lte=end)

    @staticmethod
    def _mapping_groups(rows):
        customers, countries, keys = {}, {}, {}
        for row in rows:
            codes = {str(value) for value in row.get("source_account_codes", []) if value}
            if row.get("account_id"):
                item = customers.setdefault(row["account_id"], {"id": row["account_id"], "name": row.get("account_name"), "codes": set(), "country": row.get("business_country"), "key_account": row.get("key_account_name")})
                item["codes"].update(codes)
            if row.get("business_country"):
                item = countries.setdefault(row["business_country"], {"id": row["business_country"], "name": row["business_country"], "codes": set()})
                item["codes"].update(codes)
            if row.get("key_account_id"):
                item = keys.setdefault(row["key_account_id"], {"id": row["key_account_id"], "name": row.get("key_account_name"), "codes": set()})
                item["codes"].update(codes)
        return customers, countries, keys

    @staticmethod
    def _source_totals(queryset):
        result = defaultdict(lambda: defaultdict(Decimal))
        for row in queryset.values("source_account_code", "lob").annotate(value=Sum("revenue_eur")):
            result[str(row["source_account_code"])][str(row["lob"])] += row["value"] or Decimal("0")
        return result

    @classmethod
    def _rank_dimension(cls, groups, current_query, comparison_query, total):
        current = cls._source_totals(current_query)
        previous = cls._source_totals(comparison_query)
        results = []
        for item in groups.values():
            by_lob = {lob: sum((current[code][lob] for code in item["codes"]), Decimal("0")) for lob in ALL_LOBS}
            current_value = sum(by_lob.values(), Decimal("0"))
            previous_value = sum((sum(previous[code].values(), Decimal("0")) for code in item["codes"]), Decimal("0"))
            delta = current_value - previous_value
            results.append({
                "id": item["id"], "name": item["name"], "revenue": _float(current_value),
                "previous_revenue": _float(previous_value), "absolute_delta": _float(delta),
                "relative_delta": round(_float(delta / previous_value * 100), 1) if previous_value else None,
                "share": round(_float(current_value / total * 100), 1) if total else None,
                "business_line_mix": {key: _float(by_lob[value[0]]) for key, value in BUSINESS_LINES.items()},
                "country": item.get("country"), "key_account": item.get("key_account"),
            })
        results.sort(key=lambda item: (-item["revenue"], str(item["name"] or "")))
        for rank, item in enumerate(results, 1):
            item["rank"] = rank
        return results

    def _build_core(self, revenue, publication, published_rows, selected_rows, period, business_line, source_run):
        current_all = self._range(revenue, period["start_date"], period["end_date"])
        comparison_all = self._range(revenue, period["comparison_start_date"], period["comparison_end_date"])
        selected_lob = BUSINESS_LINES[business_line][0] if business_line in BUSINESS_LINES else None
        current = current_all.filter(lob=selected_lob) if selected_lob else current_all
        comparison = comparison_all.filter(lob=selected_lob) if selected_lob else comparison_all
        current_total, comparison_total = _amount(current), _amount(comparison)
        delta = current_total - comparison_total

        current_by_lob = {row["lob"]: row["value"] or Decimal("0") for row in current_all.values("lob").annotate(value=Sum("revenue_eur"))}
        previous_by_lob = {row["lob"]: row["value"] or Decimal("0") for row in comparison_all.values("lob").annotate(value=Sum("revenue_eur"))}
        line_rows = []
        for code, (lob, label) in BUSINESS_LINES.items():
            value, previous = current_by_lob.get(lob, Decimal("0")), previous_by_lob.get(lob, Decimal("0"))
            line_delta = value - previous
            line_rows.append({
                "code": code, "lob": lob, "label": label, "revenue": _float(value),
                "comparison_revenue": _float(previous), "absolute_delta": _float(line_delta),
                "relative_delta": round(_float(line_delta / previous * 100), 1) if previous else None,
                "share": round(_float(value / sum(current_by_lob.values(), Decimal("0")) * 100), 1) if sum(current_by_lob.values(), Decimal("0")) else None,
            })
        ranked = sorted(line_rows, key=lambda item: -item["revenue"])
        ranks = {item["code"]: rank for rank, item in enumerate(ranked, 1)}
        for item in line_rows:
            item["rank"] = ranks[item["code"]]

        trend = []
        for row in current.annotate(month=TruncMonth("business_date")).values("month").annotate(value=Sum("revenue_eur")).order_by("month"):
            trend.append({"date": row["month"].isoformat(), "value": _float(row["value"])})
        comparison_trend = [
            {"date": row["month"].isoformat(), "value": _float(row["value"])}
            for row in comparison.annotate(month=TruncMonth("business_date")).values("month").annotate(value=Sum("revenue_eur")).order_by("month")
        ]
        changes = sorted(({
            "code": f"{item['code']}_change", "entity_type": "Business Line", "entity_id": item["code"],
            "entity": item["label"], "current_value": item["revenue"], "comparison_value": item["comparison_revenue"],
            "absolute_delta": item["absolute_delta"], "relative_delta": item["relative_delta"],
            "reason_code": "BUSINESS_LINE_PERIOD_CHANGE",
        } for item in line_rows), key=lambda item: -abs(item["absolute_delta"] or 0))[:5]

        customers, countries, keys = self._mapping_groups(selected_rows if (self._csv("customer_ids") or self._csv("country_ids") or self._csv("key_account_ids")) else published_rows)
        total_for_dimensions = _amount(current)
        dimensions = {
            "customers": self._rank_dimension(customers, current, comparison, total_for_dimensions),
            "countries": self._rank_dimension(countries, current, comparison, total_for_dimensions),
            "key_accounts": self._rank_dimension(keys, current, comparison, total_for_dimensions),
        }
        mapped_codes = {code for row in published_rows for code in row.get("source_account_codes", []) if code}
        mapped_revenue = _amount(current_all.filter(source_account_code__in=mapped_codes)) if mapped_codes else Decimal("0")
        all_scope_revenue = _amount(current_all)
        unallocated = all_scope_revenue - mapped_revenue
        unclassified = current_by_lob.get(UNCLASSIFIED_REVENUE_LOB, Decimal("0"))
        customer_coverage = float(mapped_revenue / all_scope_revenue * 100) if all_scope_revenue else None
        country_codes = {code for row in published_rows if row.get("business_country") for code in row.get("source_account_codes", [])}
        key_codes = {code for row in published_rows if row.get("key_account_id") for code in row.get("source_account_codes", [])}
        country_coverage = float(_amount(current_all.filter(source_account_code__in=country_codes)) / all_scope_revenue * 100) if all_scope_revenue else None
        key_coverage = float(_amount(current_all.filter(source_account_code__in=key_codes)) / all_scope_revenue * 100) if all_scope_revenue else None
        warnings = []
        if not publication:
            warnings.append("A Published Mapping version is required for Customer, Country and Key Account analysis.")
        if customer_coverage is not None and customer_coverage < 90:
            warnings.append(f"Canonical Customer coverage is {customer_coverage:.1f}%.")
        if unclassified:
            warnings.append("Some Revenue is not classified into the four governed Business Lines.")
        confidence_status = "Not Ready" if not publication else ("High" if not warnings else ("Moderate" if (customer_coverage or 0) >= 60 else "Low"))
        attention = []
        for item in line_rows:
            if item["absolute_delta"] < 0:
                attention.append({"code": "BUSINESS_LINE_DECLINE", "severity": "High", "title": f"{item['label']} Revenue declined", "entity": item["label"], "impact": abs(item["absolute_delta"]), "evidence": item})
        if unallocated:
            attention.append({"code": "UNALLOCATED_REVENUE", "severity": "High", "title": "Revenue is not assigned to published Customers", "entity": "Mapping coverage", "impact": _float(unallocated), "evidence": {"coverage": customer_coverage}})
        if unclassified:
            attention.append({"code": "UNCLASSIFIED_REVENUE", "severity": "Medium", "title": "Revenue requires Business Line classification", "entity": "Business Line", "impact": _float(unclassified), "evidence": {}})

        reconciliation_total = sum(current_by_lob.values(), Decimal("0"))
        reconciliation_difference = all_scope_revenue - reconciliation_total
        sales_review = {
            "summary": {
                "actual_revenue": _float(current_total),
                "comparison_revenue": _float(comparison_total),
                "absolute_delta": _float(delta),
                "relative_delta": round(_float(delta / comparison_total * 100), 1) if comparison_total else None,
            },
            "by_business_line": line_rows,
            "by_country": dimensions["countries"][:25],
            "by_customer": dimensions["customers"][:25],
            "concentration": self._concentration(dimensions["customers"]),
            "budget": {
                "status": "NOT_AVAILABLE",
                "message": "A certified Mining Sales budget source is not configured yet.",
            },
            "firm_orders": {
                "status": "NOT_AVAILABLE",
                "message": "Firm Orders and Sales Funnel require a governed structured source.",
            },
        }
        options = {
            "customers": [{"id": item["id"], "name": item["name"], "country": item.get("country")} for item in customers.values()],
            "countries": [{"id": item["id"], "name": item["name"]} for item in countries.values()],
            "key_accounts": [{"id": item["id"], "name": item["name"]} for item in keys.values()],
        }
        snapshot = BusinessReviewSnapshot.objects.filter(mapping_publication=publication, source_synchronization=source_run).order_by("-generated_at").first() if publication else None
        actions = BusinessReviewAction.objects.filter(snapshot=snapshot).exclude(status__in=["Completed", "Cancelled"]) if snapshot else BusinessReviewAction.objects.none()
        return {
            "ready": True,
            "mapping_ready": bool(publication),
            "mode": "published" if publication else "unmapped_business_line",
            "context": {
                "period": period["code"], "period_label": period["label"],
                "start_date": period["start_date"].isoformat(), "end_date": period["end_date"].isoformat(),
                "comparison": period["comparison"], "comparison_label": period["comparison_label"],
                "comparison_start_date": period["comparison_start_date"].isoformat() if period["comparison_start_date"] else None,
                "comparison_end_date": period["comparison_end_date"].isoformat() if period["comparison_end_date"] else None,
                "business_line": business_line, "currency": "EUR",
                "published_mapping_version": publication.version if publication else None,
            },
            "freshness": {"data_through_date": period["end_date"].isoformat(), "source_snapshot_at": source_run.completed_at, "snapshot_id": str(source_run.id)},
            "confidence": {"status": confidence_status, "customer_coverage": customer_coverage, "country_coverage": country_coverage, "key_account_coverage": key_coverage, "unallocated_revenue": _float(unallocated), "unclassified_revenue": _float(unclassified), "warnings": warnings},
            "hero": {"revenue": _float(current_total), "comparison_revenue": _float(comparison_total), "absolute_delta": _float(delta), "relative_delta": round(_float(delta / comparison_total * 100), 1) if comparison_total else None, "top_contributor": ranked[0]["label"] if ranked else None},
            "business_lines": line_rows,
            "changes": changes,
            "trend": trend,
            "comparison_trend": comparison_trend,
            "mix": line_rows,
            "bridge": [{"code": item["code"], "label": item["label"], "delta": item["absolute_delta"]} for item in line_rows],
            "dimensions": dimensions,
            "sales_review": sales_review,
            "filter_options": options,
            "attention_items": sorted(attention, key=lambda item: -item["impact"])[:6],
            "concentration": self._concentration(dimensions["customers"]),
            "reconciliation": {"status": "RECONCILED" if abs(reconciliation_difference) <= Decimal("0.01") else "FAILED", "difference": _float(reconciliation_difference), "tolerance": 0.01},
            "actions_summary": {"open": actions.count(), "critical": actions.filter(priority="Critical").count(), "overdue": actions.filter(due_date__lt=timezone.localdate()).count()},
            "snapshot_id": str(snapshot.id) if snapshot else None,
        }

    @staticmethod
    def _concentration(customers):
        total = sum(item["revenue"] for item in customers)
        values = sorted((item["revenue"] for item in customers), reverse=True)
        share = lambda count: round(sum(values[:count]) / total * 100, 1) if total else None
        return {"top_1_share": share(1), "top_5_share": share(5), "top_10_share": share(10)}

    def _visit(self, core, source_run):
        context = core["context"]
        filter_hash = hashlib.sha256(json.dumps(context, sort_keys=True).encode("utf-8")).hexdigest()
        previous = BusinessCommandCenterUserVisit.objects.filter(user=self.user, filter_hash=filter_hash).first()
        last_metrics = previous.last_seen_metrics_json if previous else {}
        since = []
        previous_revenue = last_metrics.get("revenue")
        if previous_revenue is not None and previous_revenue != core["hero"]["revenue"]:
            since.append({"code": "REVENUE_CHANGED", "title": "Revenue changed since your last visit", "absolute_delta": core["hero"]["revenue"] - previous_revenue})
        BusinessCommandCenterUserVisit.objects.update_or_create(
            user=self.user, filter_hash=filter_hash,
            defaults={"snapshot_id": core.get("snapshot_id"), "source_synchronization": source_run, "last_seen_metrics_json": {"revenue": core["hero"]["revenue"], "data_through_date": core["freshness"]["data_through_date"]}},
        )
        return {"filter_hash": filter_hash, "previous_visit_at": previous.last_opened_at if previous else None, "items": since}

    def bootstrap(self):
        revenue, publication, published_rows, selected_rows, period, business_line, source_run = self._context()
        scope_key = {
            "user": self.user.pk, "source": str(source_run.pk), "publication": publication.version if publication else None,
            "period": {key: str(value) for key, value in period.items()}, "business_line": business_line,
            "customers": sorted(self._csv("customer_ids")), "countries": sorted(self._csv("country_ids")), "keys": sorted(self._csv("key_account_ids")),
        }
        cache_key = "business-command-center:" + hashlib.sha256(json.dumps(scope_key, sort_keys=True).encode("utf-8")).hexdigest()
        core = cache.get(cache_key)
        if core is None:
            core = self._build_core(revenue, publication, published_rows, selected_rows, period, business_line, source_run)
            cache.set(cache_key, core, self.CACHE_SECONDS)
        result = copy.deepcopy(core)
        result["since_last_visit"] = self._visit(result, source_run)
        watchlist = BusinessCommandCenterWatchlist.objects.filter(user=self.user, active=True)
        result["watchlist"] = [{"id": str(item.id), "entity_type": item.entity_type, "entity_id": item.entity_id, "display_name": item.display_name} for item in watchlist]
        return result
