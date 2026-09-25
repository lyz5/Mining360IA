from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from django.core.cache import cache
from django.db.models import Count, Max, Q, Sum
from django.db.models.functions import TruncDay, TruncMonth
from django.utils import timezone

from .business_mapping_country_scope import operating_country_label

from .business_mapping_access_service import authorized_account_codes, authorized_minesite_names
from .business_mapping_normalization_service import normalize_business_name
from .business_mapping_source_service import BUSINESS_REVENUE_DIVISIONS, MINING_DIVISION, MINING_REVENUE_LOBS, UNCLASSIFIED_REVENUE_LOB
from .business_review_access_service import filter_published_rows
from .models import (
    BusinessAccount,
    EquipmentFleetAnalysis,
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
GROWTH_MEANINGFUL_MINIMUM_EUR = Decimal("1000")


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


def _growth(current, previous):
    if previous == 0:
        if current == 0:
            return None, "no_change"
        return None, "new" if current > 0 else "not_meaningful"
    if previous < 0 or abs(previous) < GROWTH_MEANINGFUL_MINIMUM_EUR:
        return None, "not_meaningful"
    return round(_float((current - previous) / abs(previous) * 100), 1), "comparable"


class BusinessRevenuePeriodService:
    PERIODS = {"ytd", "current_month", "last_year", "2024", "2023", "custom"}
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
        if period == "2023":
            comparison = "none"
        if period == "ytd":
            start, end = date(latest_date.year, 1, 1), latest_date
            label = f"YTD {latest_date.year}"
        elif period == "last_year":
            start, end = date(latest_date.year - 1, 1, 1), date(latest_date.year - 1, 12, 31)
            label = str(latest_date.year - 1)
        elif period == "current_month":
            start, end = latest_date.replace(day=1), latest_date
            label = latest_date.strftime("MTD %b %Y")
        elif period in {"2024", "2023"}:
            selected_year = int(period)
            start, end = date(selected_year, 1, 1), date(selected_year, 12, 31)
            label = period
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

    def _division_scope(self):
        scope = str(self.params.get("division_scope") or "mining").strip().lower()
        if scope not in {"mining", "all_divisions"}:
            raise BusinessCommandCenterInputError("The selected Division scope is not supported.")
        return scope

    def _context(self):
        division_scope = self._division_scope()
        division_codes = tuple(BUSINESS_REVENUE_DIVISIONS) if division_scope == "all_divisions" else (MINING_DIVISION,)
        revenue = RevenueSourceSnapshot.objects.filter(active=True, division__in=division_codes)
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
        published_rows = self._with_canonical_names(published_rows)
        customers = self._csv("customer_ids")
        customer_groups = self._csv("customer_group_ids")
        countries, key_accounts = self._csv("country_ids"), self._csv("key_account_ids")
        selected_rows = published_rows
        if customers:
            selected_rows = [row for row in selected_rows if row.get("account_id") in customers]
        if customer_groups:
            selected_rows = [row for row in selected_rows if row.get("customer_country_group_id") in customer_groups]
        if countries:
            selected_rows = [row for row in selected_rows if row.get("business_country") in countries]
        if key_accounts:
            selected_rows = [row for row in selected_rows if row.get("key_account_id") in key_accounts]
        if customers or customer_groups or countries or key_accounts:
            selected_codes = {str(code) for row in selected_rows for code in row.get("source_account_codes", []) if code}
            revenue = revenue.filter(source_account_code__in=selected_codes) if selected_codes else revenue.none()
        business_line = str(self.params.get("business_line") or "all_business").strip().lower()
        if business_line not in {"all_business", *BUSINESS_LINES}:
            raise BusinessCommandCenterInputError("The selected Business Line is not supported.")
        return revenue, publication, published_rows, selected_rows, period, business_line, source_row.synchronization_run

    @staticmethod
    def _with_canonical_names(rows):
        """Refresh labels only; identities, scope and allocations stay published."""
        ids = {}
        for row in rows:
            try:
                ids[row.get("account_id")] = UUID(str(row.get("account_id")))
            except (ValueError, TypeError, AttributeError):
                continue
        names = dict(BusinessAccount.objects.filter(pk__in=ids.values()).values_list("pk", "canonical_account_name"))
        result = []
        group_names = defaultdict(set)
        unresolved_groups = set()
        for row in rows:
            item = dict(row)
            name = names.get(ids.get(row.get("account_id")))
            if name:
                item["account_name"] = name
            result.append(item)
            if item.get("customer_country_group_id"):
                group_names[item["customer_country_group_id"]].add(item.get("account_name"))
                if not name:
                    unresolved_groups.add(item["customer_country_group_id"])
        for item in result:
            labels = group_names.get(item.get("customer_country_group_id"), set())
            if item.get("customer_country_group_id") not in unresolved_groups and len(labels) == 1 and None not in labels and "" not in labels:
                item["customer_country_group_name"] = next(iter(labels))
        return result

    def latest_business_date(self):
        """Return the authorized Revenue date without recording a Command Center visit."""
        _revenue, _publication, _published, _selected, period, _line, _run = self._context()
        return period["end_date"]

    def entity_fleet(self, dimension, entity_id):
        fields = {"customers": "account_id", "key_accounts": "key_account_id", "countries": "business_country"}
        if dimension not in fields:
            raise BusinessCommandCenterInputError("Unsupported Fleet dimension.")
        _revenue, _publication, _published, selected, _period, _line, _run = self._context()
        rows = [row for row in selected if str(row.get(fields[dimension]) or "") == str(entity_id)]
        if not rows:
            raise BusinessCommandCenterInputError("This entity is not available in the selected scope.")
        sites = {name for row in rows for name in [row.get("minesite_name"), *(row.get("minesite_names") or [])] if name}
        scope_label = "Selected entity"
        if not sites and dimension == "customers":
            group_ids = {row.get("customer_country_group_id") for row in rows if row.get("customer_country_group_id")}
            peers = [row for row in selected if row.get("customer_country_group_id") in group_ids]
            sites = {name for row in peers for name in [row.get("minesite_name"), *(row.get("minesite_names") or [])] if name}
            if sites:
                scope_label = "Published customer group: " + ", ".join(sorted({row.get("customer_country_group_name") or "Customer group" for row in rows}))
        allowed = authorized_minesite_names(self.user)
        if allowed is not None:
            allowed = {name.casefold() for name in allowed}
            sites = {name for name in sites if name.casefold() in allowed}
        fleet = EquipmentFleetAnalysis.objects.filter(active=True, normalized_site__in=[normalize_business_name(name) for name in sites])
        total = fleet.count()
        return {"linked": bool(sites), "count": total, "sites": sorted(sites), "scope_label": scope_label,
                "as_of": fleet.aggregate(value=Max("source_last_seen_at"))["value"],
                "models": list(fleet.values("model").annotate(count=Count("pk")).order_by("-count", "model")),
                "equipment": list(fleet.order_by("site", "model", "equipment", "pk").values("site", "model", "equipment", "serial_number", "source_status")[:200]),
                "limit": 200}

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
                item = customers.setdefault(row["account_id"], {"id": row["account_id"], "name": row.get("account_name"), "code": row.get("account_code"), "codes": set(), "country": operating_country_label(row.get("business_country")), "key_account": row.get("key_account_name")})
                item["codes"].update(codes)
            if row.get("business_country"):
                item = countries.setdefault(row["business_country"], {"id": row["business_country"], "name": operating_country_label(row["business_country"]), "codes": set()})
                item["codes"].update(codes)
            if row.get("key_account_id"):
                item = keys.setdefault(row["key_account_id"], {"id": row["key_account_id"], "name": row.get("key_account_name"), "codes": set()})
                item["codes"].update(codes)
        return customers, countries, keys

    @staticmethod
    def _customer_country_groups(rows):
        groups = {}
        for row in rows:
            group_id = row.get("customer_country_group_id")
            if not group_id:
                continue
            item = groups.setdefault(group_id, {
                "id": group_id,
                "name": row.get("customer_country_group_name"),
                "country": operating_country_label(row.get("business_country")),
                "codes": set(),
            })
            item["codes"].update(str(code) for code in row.get("source_account_codes", []) if code)
        return groups

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
            previous_by_lob = {lob: sum((previous[code][lob] for code in item["codes"]), Decimal("0")) for lob in ALL_LOBS}
            current_value = sum(by_lob.values(), Decimal("0"))
            previous_value = sum(previous_by_lob.values(), Decimal("0"))
            delta = current_value - previous_value
            relative_delta, growth_status = _growth(current_value, previous_value)
            results.append({
                "id": item["id"], "name": item["name"], "revenue": _float(current_value),
                "previous_revenue": _float(previous_value), "absolute_delta": _float(delta),
                "relative_delta": relative_delta, "growth_status": growth_status,
                "share": round(_float(current_value / total * 100), 1) if total else None,
                "business_line_mix": {key: _float(by_lob[value[0]]) for key, value in BUSINESS_LINES.items()},
                "comparison_business_line_mix": {key: _float(previous_by_lob[value[0]]) for key, value in BUSINESS_LINES.items()},
                "code": item.get("code"), "country": item.get("country"), "key_account": item.get("key_account"),
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
            relative_delta, growth_status = _growth(value, previous)
            line_rows.append({
                "code": code, "lob": lob, "label": label, "revenue": _float(value),
                "comparison_revenue": _float(previous), "absolute_delta": _float(line_delta),
                "relative_delta": relative_delta, "growth_status": growth_status,
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
        current_month_start = period["end_date"].replace(day=1)
        daily_start = max(period["start_date"], current_month_start)
        daily_trend = [
            {"date": row["day"].isoformat(), "value": _float(row["value"])}
            for row in current.filter(business_date__gte=daily_start).annotate(day=TruncDay("business_date")).values("day").annotate(value=Sum("revenue_eur")).order_by("day")
        ]
        comparison_daily_trend = []
        if period["comparison_end_date"]:
            comparison_month_start = period["comparison_end_date"].replace(day=1)
            comparison_daily_start = max(period["comparison_start_date"], comparison_month_start)
            comparison_daily_trend = [
                {"date": row["day"].isoformat(), "value": _float(row["value"])}
                for row in comparison.filter(business_date__gte=comparison_daily_start).annotate(day=TruncDay("business_date")).values("day").annotate(value=Sum("revenue_eur")).order_by("day")
            ]
        changes = sorted(({
            "code": f"{item['code']}_change", "entity_type": "Business Line", "entity_id": item["code"],
            "entity": item["label"], "current_value": item["revenue"], "comparison_value": item["comparison_revenue"],
            "absolute_delta": item["absolute_delta"], "relative_delta": item["relative_delta"],
            "reason_code": "BUSINESS_LINE_PERIOD_CHANGE", "growth_status": item["growth_status"],
        } for item in line_rows if item["absolute_delta"] or item["revenue"] or item["comparison_revenue"]), key=lambda item: -abs(item["absolute_delta"] or 0))[:5]
        previous_data_date = period["end_date"] - timedelta(days=1)
        latest_day_by_lob = {
            row["lob"]: row["value"] or Decimal("0")
            for row in current_all.filter(business_date=period["end_date"]).values("lob").annotate(value=Sum("revenue_eur"))
        }
        since_yesterday = []
        for item in line_rows:
            day_value = latest_day_by_lob.get(item["lob"], Decimal("0"))
            if selected_lob and item["lob"] != selected_lob:
                continue
            if day_value:
                since_yesterday.append({
                    "code": f"{item['code']}_since_yesterday",
                    "entity_type": "Business Line",
                    "entity_id": item["code"],
                    "entity": item["label"],
                    "title": f"{item['label']} Revenue added on the latest data day",
                    "current_value": item["revenue"],
                    "comparison_value": item["revenue"] - _float(day_value),
                    "absolute_delta": _float(day_value),
                    "relative_delta": None,
                    "growth_status": "not_meaningful",
                    "reason_code": "REVENUE_SINCE_PREVIOUS_DATA_DAY",
                })
        since_yesterday.sort(key=lambda item: -abs(item["absolute_delta"] or 0))

        has_filters = any(self._csv(key) for key in ("customer_ids", "customer_group_ids", "country_ids", "key_account_ids"))
        customers, countries, keys = self._mapping_groups(selected_rows if has_filters else published_rows)
        total_for_dimensions = _amount(current)
        all_dimensions = {
            "customers": self._rank_dimension(customers, current, comparison, total_for_dimensions),
            "countries": self._rank_dimension(countries, current, comparison, total_for_dimensions),
            "key_accounts": self._rank_dimension(keys, current, comparison, total_for_dimensions),
        }
        legacy = str(self.params.get("ui") or "").strip().lower() == "legacy"
        dimensions = all_dimensions if legacy else {key: rows[:5] for key, rows in all_dimensions.items()}
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
                "relative_delta": _growth(current_total, comparison_total)[0],
            },
            "by_business_line": line_rows,
            "by_country": all_dimensions["countries"][:25],
            "by_customer": all_dimensions["customers"][:25],
            "concentration": self._concentration(all_dimensions["customers"]),
            "budget": {
                "status": "NOT_AVAILABLE",
                "message": "A certified Mining Sales budget source is not configured yet.",
            },
            "firm_orders": {
                "status": "NOT_AVAILABLE",
                "message": "Firm Orders and Sales Funnel require a governed structured source.",
            },
        }
        selected_customer_group_ids = self._csv("customer_group_ids")
        selected_key_ids = self._csv("key_account_ids")
        customer_groups = self._customer_country_groups(published_rows)
        options = {
            "customers": [{"id": item["id"], "name": item["name"], "country": item.get("country")} for item in customer_groups.values() if legacy or item["id"] in selected_customer_group_ids],
            "countries": [{"id": item["id"], "name": item["name"]} for item in countries.values()],
            "key_accounts": [{"id": item["id"], "name": item["name"]} for item in keys.values() if legacy or item["id"] in selected_key_ids],
        }
        snapshot = BusinessReviewSnapshot.objects.filter(mapping_publication=publication, source_synchronization=source_run).order_by("-generated_at").first() if publication else None
        actions = BusinessReviewAction.objects.filter(snapshot=snapshot).exclude(status__in=["Completed", "Cancelled"]) if snapshot else BusinessReviewAction.objects.none()
        context_signature = {
            "user": self.user.pk,
            "source": str(source_run.pk),
            "publication": publication.version if publication else None,
            "period": period["code"],
            "start": period["start_date"].isoformat(),
            "end": period["end_date"].isoformat(),
            "comparison": period["comparison"],
            "business_line": business_line,
            "division_scope": self._division_scope(),
            "customers": sorted(self._csv("customer_ids")),
            "customer_groups": sorted(self._csv("customer_group_ids")),
            "countries": sorted(self._csv("country_ids")),
            "keys": sorted(self._csv("key_account_ids")),
        }
        context_id = hashlib.sha256(json.dumps(context_signature, sort_keys=True).encode("utf-8")).hexdigest()[:24]
        payload = {
            "ready": True,
            "mapping_ready": bool(publication),
            "mode": "published" if publication else "unmapped_business_line",
            "context": {
                "context_id": context_id,
                "period": period["code"], "period_label": period["label"],
                "start_date": period["start_date"].isoformat(), "end_date": period["end_date"].isoformat(),
                "comparison": period["comparison"], "comparison_label": period["comparison_label"],
                "comparison_start_date": period["comparison_start_date"].isoformat() if period["comparison_start_date"] else None,
                "comparison_end_date": period["comparison_end_date"].isoformat() if period["comparison_end_date"] else None,
                "business_line": business_line, "currency": "EUR",
                "division_scope": self._division_scope(),
                "division_codes": list(BUSINESS_REVENUE_DIVISIONS) if self._division_scope() == "all_divisions" else [MINING_DIVISION],
                "published_mapping_version": publication.version if publication else None,
            },
            "freshness": {"data_through_date": period["end_date"].isoformat(), "source_snapshot_at": source_run.completed_at, "snapshot_id": str(source_run.id)},
            "confidence": {"status": confidence_status, "customer_coverage": customer_coverage, "country_coverage": country_coverage, "key_account_coverage": key_coverage, "unallocated_revenue": _float(unallocated), "unclassified_revenue": _float(unclassified), "warnings": warnings},
            "hero": {"revenue": _float(current_total), "comparison_revenue": _float(comparison_total), "absolute_delta": _float(delta), "relative_delta": _growth(current_total, comparison_total)[0], "growth_status": _growth(current_total, comparison_total)[1], "top_contributor": ranked[0]["label"] if ranked else None},
            "business_lines": line_rows,
            "changes": changes,
            "trend": trend,
            "comparison_trend": comparison_trend,
            "daily_trend": daily_trend,
            "comparison_daily_trend": comparison_daily_trend,
            "since_yesterday": {
                "from_date": previous_data_date.isoformat(),
                "through_date": period["end_date"].isoformat(),
                "items": since_yesterday[:5],
            },
            "mix": line_rows,
            "bridge": [{"code": item["code"], "label": item["label"], "delta": item["absolute_delta"]} for item in line_rows],
            "dimensions": dimensions,
            "filter_options": options,
            "attention_items": sorted(attention, key=lambda item: -item["impact"])[:6],
            "concentration": self._concentration(all_dimensions["customers"]),
            "reconciliation": {"status": "RECONCILED" if abs(reconciliation_difference) <= Decimal("0.01") else "FAILED", "difference": _float(reconciliation_difference), "tolerance": 0.01},
            "actions_summary": {"open": actions.count(), "critical": actions.filter(priority="Critical").count(), "overdue": actions.filter(due_date__lt=timezone.localdate()).count()},
            "snapshot_id": str(snapshot.id) if snapshot else None,
        }
        if legacy:
            payload["sales_review"] = sales_review
        return payload

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
            "canonical_labels": [(row.get("account_id"), row.get("account_name"), row.get("customer_country_group_name")) for row in published_rows],
            "user": self.user.pk, "source": str(source_run.pk), "publication": publication.version if publication else None,
            "period": {key: str(value) for key, value in period.items()}, "business_line": business_line,
            "division_scope": self._division_scope(),
            "customers": sorted(self._csv("customer_ids")), "customer_groups": sorted(self._csv("customer_group_ids")),
            "countries": sorted(self._csv("country_ids")), "keys": sorted(self._csv("key_account_ids")),
        }
        cache_key = "business-command-center:v2:" + hashlib.sha256(json.dumps(scope_key, sort_keys=True).encode("utf-8")).hexdigest()
        core = None if str(self.params.get("refresh", "")) == "1" else cache.get(cache_key)
        if core is None:
            core = self._build_core(revenue, publication, published_rows, selected_rows, period, business_line, source_run)
            cache.set(cache_key, core, self.CACHE_SECONDS)
        result = copy.deepcopy(core)
        result['source_sync_id'] = str(source_run.pk)
        result["since_last_visit"] = self._visit(result, source_run)
        watchlist = BusinessCommandCenterWatchlist.objects.filter(user=self.user, active=True)
        customer_names = {row.get("account_id"): row.get("account_name") for row in published_rows}
        result["watchlist"] = [{"id": str(item.id), "entity_type": item.entity_type, "entity_id": item.entity_id,
                               "display_name": customer_names.get(item.entity_id, item.display_name) if item.entity_type == "customer" else item.display_name} for item in watchlist]
        return result

    def revenue_explorer(self):
        revenue, publication, published_rows, selected_rows, period, business_line, source_run = self._context()
        current_all = self._range(revenue, period["start_date"], period["end_date"])
        comparison_all = self._range(revenue, period["comparison_start_date"], period["comparison_end_date"])
        selected_lob = BUSINESS_LINES[business_line][0] if business_line in BUSINESS_LINES else None
        current = current_all.filter(lob=selected_lob) if selected_lob else current_all
        comparison = comparison_all.filter(lob=selected_lob) if selected_lob else comparison_all
        dimension = str(self.params.get("dimension") or "customers").strip().lower()
        groups = self._mapping_groups(selected_rows if any(self._csv(key) for key in ("customer_ids", "customer_group_ids", "country_ids", "key_account_ids")) else published_rows)
        group_map = {"customers": groups[0], "countries": groups[1], "key_accounts": groups[2]}
        if dimension not in group_map:
            raise BusinessCommandCenterInputError("The selected Revenue Explorer dimension is not supported.")
        rows = self._rank_dimension(group_map[dimension], current, comparison, _amount(current))
        mode = str(self.params.get("ranking") or "revenue").strip().lower()
        sorters = {
            "revenue": lambda item: -(item["revenue"] or 0),
            "growth": lambda item: -(item["absolute_delta"] or 0),
            "decline": lambda item: item["absolute_delta"] or 0,
            "absolute_increase": lambda item: -(item["absolute_delta"] or 0),
            "absolute_decrease": lambda item: item["absolute_delta"] or 0,
        }
        if mode not in sorters:
            raise BusinessCommandCenterInputError("The selected ranking mode is not supported.")
        rows.sort(key=lambda item: (sorters[mode](item), str(item["name"] or "")))
        try:
            requested_limit = str(self.params.get("limit") or "10").strip().lower()
            limit = len(rows) if requested_limit == "all" else min(100, max(5, int(requested_limit)))
        except (TypeError, ValueError):
            limit = 10
        for rank, item in enumerate(rows, 1):
            item["rank"] = rank
        duplicate_names = defaultdict(int)
        for item in rows:
            duplicate_names[str(item.get("name") or "").casefold()] += 1
        for item in rows:
            duplicate = duplicate_names[str(item.get("name") or "").casefold()] > 1
            item["display_name"] = f"{item['name']} · {item['code']}" if dimension != "customers" and duplicate and item.get("code") else item.get("name")
        return {
            "context_id": self.bootstrap()["context"]["context_id"],
            "dimension": dimension,
            "ranking": mode,
            "count": len(rows),
            "results": rows[:limit],
        }

    def search_entities(self, entity_type):
        revenue, _publication, published_rows, _selected_rows, period, business_line, _run = self._context()
        groups = self._mapping_groups(published_rows)
        group_map = {"customers": self._customer_country_groups(published_rows), "key_accounts": groups[2]}
        if entity_type not in group_map:
            raise BusinessCommandCenterInputError("The selected search dimension is not supported.")
        query = str(self.params.get("q") or "").strip().casefold()
        if len(query) == 1:
            return {"results": [], "has_more": False}
        current = self._range(revenue, period["start_date"], period["end_date"])
        selected_lob = BUSINESS_LINES[business_line][0] if business_line in BUSINESS_LINES else None
        if selected_lob:
            current = current.filter(lob=selected_lob)
        source_totals = self._source_totals(current)
        matches = []
        for item in group_map[entity_type].values():
            haystack = " ".join(str(value or "") for value in (item.get("name"), item.get("id"), item.get("country"))).casefold()
            if not query or query in haystack:
                amount = sum((sum(source_totals[code].values(), Decimal("0")) for code in item["codes"]), Decimal("0"))
                matches.append({"id": item["id"], "name": item.get("name"), "country": item.get("country"), "revenue": _float(amount)})
        if query:
            matches.sort(key=lambda item: (
                not str(item.get("name") or "").casefold().startswith(query),
                -(item["revenue"] or 0),
                str(item.get("name") or ""),
            ))
        else:
            matches.sort(key=lambda item: (-(item["revenue"] or 0), str(item.get("name") or "")))
        limit = 30 if not query else 20
        return {"results": matches[:limit], "has_more": len(matches) > limit}

    def resolve_filter_mentions(self, text):
        """Resolve published, authorized executive dimensions mentioned in free text."""
        _revenue, _publication, published_rows, _selected_rows, _period, _line, _run = self._context()
        customers, countries, key_accounts = self._mapping_groups(published_rows)
        groups = {
            "customer_group_ids": self._customer_country_groups(published_rows),
            "country_ids": countries,
            "key_account_ids": key_accounts,
        }
        # Technical account suffixes distinguish published country/source groups,
        # not the customer requested in a question with no such qualifier.
        # Select all IDs only when both the published customer label and the
        # published Key Account agree. Published rows are already access-filtered.
        if not re.search(r"miningaccounts\s*:", str(text), re.IGNORECASE):
            customer_groups = groups["customer_group_ids"]
            families = defaultdict(list)
            owners = defaultdict(set)
            for row in published_rows:
                owners[row.get("customer_country_group_id")].add(row.get("key_account_id"))
            for item in customer_groups.values():
                label = re.sub(r"\s+·\s+MININGACCOUNTS:\d+-\d+\s*$", "", str(item.get("name") or ""), flags=re.IGNORECASE).strip()
                families[label.casefold()].append((label, item))
            combined = {}
            for family in families.values():
                key_ids = set().union(*(owners[item["id"]] for _, item in family))
                if len(family) > 1 and len(key_ids) == 1 and None not in key_ids and "" not in key_ids:
                    ids = sorted(str(item["id"]) for _, item in family)
                    identifier = ",".join(ids)
                    combined[identifier] = {
                        "id": identifier, "name": family[0][0],
                        "country": "", "group_count": len(ids),
                    }
                else:
                    combined.update({item["id"]: item for _, item in family})
            groups["customer_group_ids"] = combined
        normalized_text = re.sub(r"[^a-z0-9]+", " ", str(text or "").casefold()).strip()
        padded_text = f" {normalized_text} "
        resolved = {}
        ambiguities = {}
        resolved_scope = {}
        ignored_words = {
            "business", "ca", "centre", "center", "command", "courant", "current",
            "quel", "quelle", "revenue", "revenu", "parts", "pieces", "machine",
            "service", "rental", "ventes", "vente", "year", "ytd",
            "what", "which", "the", "for", "our", "are", "was", "were", "how",
            "much", "show", "tell", "give", "please", "about", "total", "sales",
            "sold", "this", "last", "month", "pour", "les", "des", "est", "sont",
            "combien", "donne", "moi", "montre", "annee", "vendu", "nous",
        }
        query_words = {
            word for word in normalized_text.split()
            if len(word) >= 3 and word not in ignored_words and not word.isdigit()
        }
        for parameter, options in groups.items():
            matches = []
            for item in options.values():
                name = re.sub(r"[^a-z0-9]+", " ", str(item.get("name") or "").casefold()).strip()
                if name and f" {name} " in padded_text:
                    matches.append((len(name), str(item["id"]), item))
            if matches:
                longest = max(length for length, _, _ in matches)
                best = [item for length, _, item in matches if length == longest]
                if len(best) > 1:
                    ambiguities[parameter] = [{"id":str(item["id"]), "name":item.get("name"), "country":item.get("country")} for item in best[:10]]
                    continue
                resolved[parameter] = str(best[0]["id"])
                resolved_scope[parameter] = {"name":best[0].get("name"), "group_count":best[0].get("group_count", 1)}
                continue
            partial = []
            for item in options.values():
                name_words = set(re.sub(r"[^a-z0-9]+", " ", str(item.get("name") or "").casefold()).split())
                if query_words & name_words:
                    partial.append(item)
            if len(partial) == 1:
                resolved[parameter] = str(partial[0]["id"])
                resolved_scope[parameter] = {"name":partial[0].get("name"), "group_count":partial[0].get("group_count", 1)}
            elif len(partial) > 1:
                ambiguities[parameter] = [
                    {"id": str(item["id"]), "name": item.get("name"), "country": item.get("country")}
                    for item in partial[:10]
                ]
        return {"filters": resolved, "ambiguities": ambiguities, "scope": resolved_scope}
