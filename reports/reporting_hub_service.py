from __future__ import annotations

from datetime import datetime, timedelta

from django.urls import reverse
from django.utils import timezone

from .models import (
    PowerBIReport as ConfiguredPowerBIReport,
    ReportCategory,
    ReportingReportPreference,
    UserReportActivity,
    UserReportFavorite,
)
from .report_visual_identity import CATEGORY_DEFAULTS, ReportVisualIdentityResolver


CATEGORY_LABELS = dict(ReportingReportPreference.CATEGORIES)


def _default_metadata(name: str) -> dict:
    normalized = str(name or "").casefold()
    mappings = (
        (("fuel monitoring",), "fuel_connectivity", "Track fuel consumption, idle time, connectivity and operational efficiency.", ["Fuel", "Idle"], "fuel_monitoring", "droplet", "blue", ""),
        (("connected assets", "poca"), "fuel_connectivity", "Monitor fleet connectivity and identify assets with missing data.", ["Connectivity", "Fleet"], "connectivity", "signal", "blue", ""),
        (("sos", "oil interval"), "maintenance_reliability", "Analyze oil-sample results, alerts and emerging maintenance risks.", ["SOS", "Maintenance"], "sos_analysis", "flask", "purple", ""),
        (("aftermarket", "parts"), "parts_aftermarket", "Track parts revenue, customer performance and aftermarket opportunities.", ["Parts", "Revenue"], "parts_aftermarket", "package", "rose", ""),
        (("monthly",), "management_reports", "Review consolidated monthly fleet KPIs and performance indicators.", ["Monthly Review", "Management"], "monthly_report", "calendar", "slate", "Executive"),
        (("prime mover",), "operations", "Monitor machine operational status and submit MineSite updates.", ["Prime Movers", "Status"], "prime_movers", "engine", "amber", "Interactive"),
        (("operator induced",), "operations", "Analyze operator-induced events and their impact on fleet performance.", ["Operator Events", "Downtime"], "operator_induced", "hard-hat", "amber", ""),
        (("logistics",), "operations", "Monitor operational status, logistics activity and site movement.", ["Operations", "Logistics"], "logistics", "truck", "amber", ""),
        (("lcc", "lifecycle cost"), "lifecycle_cost", "Monitor equipment lifecycle cost, cost drivers and ownership performance.", ["Lifecycle Cost", "Financial"], "lifecycle_cost", "calculator", "cyan", ""),
        (("fleet", "fpr"), "fleet_performance", "Monitor availability, reliability, downtime and fleet performance.", ["Availability", "Reliability"], "fleet_performance", "activity", "emerald", ""),
    )
    for terms, category, description, tags, illustration, icon, accent, badge in mappings:
        if any(term in normalized for term in terms):
            return {
                "category": category, "description": description, "tags": tags,
                "illustration": illustration, "icon": icon, "accent": accent, "badge": badge,
            }
    return {
        "category": "other",
        "description": "Open this analytical report to explore its governed business insights.",
        "tags": ["Analytics"],
        "illustration": "", "icon": "chart", "accent": "yellow", "badge": "",
    }


def ensure_catalog_preferences(reports, *, user=None) -> dict[str, ReportingReportPreference]:
    report_ids = [str(report.id) for report in reports if getattr(report, "id", None)]
    existing = {
        item.report_id: item
        for item in ReportingReportPreference.objects.filter(report_id__in=report_ids)
    }
    for position, report in enumerate(reports):
        report_id = str(report.id)
        if report_id in existing:
            continue
        metadata = _default_metadata(report.display_name or report.name)
        defaults = {
            "report_name": report.name,
            "display_name": report.display_name or report.name,
            "description": metadata["description"],
            "short_description": metadata["description"],
            "category": metadata["category"],
            "tags_json": metadata["tags"],
            "illustration_code": metadata["illustration"],
            "icon_code": metadata["icon"],
            "accent_code": metadata["accent"],
            "card_badge": metadata["badge"],
            "visual_identity_status": "needs_review",
            "display_order": position,
        }
        if getattr(user, "is_authenticated", False):
            defaults["updated_by"] = user
        ReportingReportPreference.objects.get_or_create(
            report_id=report_id,
            defaults=defaults,
        )

    if len(existing) != len(report_ids):
        existing = {
            item.report_id: item
            for item in ReportingReportPreference.objects.filter(report_id__in=report_ids)
        }

    for report in reports:
        preference = existing.get(str(report.id))
        if not preference:
            continue
        metadata = _default_metadata(preference.display_name or report.display_name or report.name)
        update_fields = []
        if not preference.report_name:
            preference.report_name = report.name
            update_fields.append("report_name")
        if not preference.display_name:
            preference.display_name = report.display_name or report.name
            update_fields.append("display_name")
        if not preference.description:
            preference.description = metadata["description"]
            update_fields.append("description")
        if not preference.short_description:
            preference.short_description = preference.description or metadata["description"]
            update_fields.append("short_description")
        if not preference.tags_json:
            preference.tags_json = metadata["tags"]
            update_fields.append("tags_json")
        if preference.category == "other" and metadata["category"] != "other":
            preference.category = metadata["category"]
            update_fields.append("category")
        for field, key in (("illustration_code", "illustration"), ("icon_code", "icon"), ("accent_code", "accent"), ("card_badge", "badge")):
            if not getattr(preference, field) and metadata[key]:
                setattr(preference, field, metadata[key])
                update_fields.append(field)
        if update_fields:
            preference.save(update_fields=[*update_fields, "updated_at"])
    return existing


def _parsed_refresh(value: str):
    try:
        parsed = datetime.strptime(str(value or ""), "%Y-%m-%d %I:%M %p")
        return timezone.make_aware(parsed, timezone.get_current_timezone())
    except (TypeError, ValueError):
        return None


def _relative_time(value) -> str:
    if not value:
        return "Refresh history is unavailable"
    seconds = max(0, int((timezone.now() - value).total_seconds()))
    if seconds < 60:
        return "Refreshed just now"
    if seconds < 3600:
        minutes = seconds // 60
        return f"Refreshed {minutes} minute{'s' if minutes != 1 else ''} ago"
    if seconds < 86400:
        hours = seconds // 3600
        return f"Refreshed {hours} hour{'s' if hours != 1 else ''} ago"
    days = seconds // 86400
    return f"Refreshed {days} day{'s' if days != 1 else ''} ago"


def normalized_status(raw_status: str, last_refresh: str, threshold_hours: int | None) -> dict:
    normalized = str(raw_status or "").casefold().replace(" ", "")
    refreshed_at = _parsed_refresh(last_refresh)
    if normalized in {"unknown", "inprogress", "running", "notstarted", "refreshing"}:
        return {"code": "refreshing", "label": "Refreshing", "detail": "Refresh in progress"}
    if normalized == "failed":
        return {"code": "failed", "label": "Failed", "detail": "Latest refresh needs attention"}
    if normalized == "completed":
        if threshold_hours and refreshed_at and timezone.now() - refreshed_at > timedelta(hours=threshold_hours):
            return {"code": "stale", "label": "Stale", "detail": "Refresh is outside its expected schedule"}
        return {"code": "healthy", "label": "Healthy", "detail": _relative_time(refreshed_at)}
    return {"code": "no_refresh", "label": "No Refresh", "detail": "No refresh history available"}


class ReportingHubService:
    def __init__(self, user, reports, *, personalization_enabled=True):
        self.user = user
        self.reports = list(reports)
        self.personalization_enabled = personalization_enabled

    def build(self, params=None) -> dict:
        params = params or {}
        ensure_catalog_preferences(self.reports, user=self.user)
        preferences = {
            item.report_id: item
            for item in ReportingReportPreference.objects.filter(
                report_id__in=[str(report.id) for report in self.reports]
            ).select_related("selected_visual_asset")
        }
        configured = {
            item.report_id: item
            for item in ConfiguredPowerBIReport.objects.filter(
                report_id__in=[str(report.id) for report in self.reports],
                is_active=True,
            )
        }
        category_configurations = {
            item.code: item for item in ReportCategory.objects.filter(active=True)
        }
        favorite_ids = set(UserReportFavorite.objects.filter(
            user=self.user,
            report__is_visible=True,
        ).values_list("report__report_id", flat=True))
        cards = []
        for report in self.reports:
            report_id = str(report.id)
            preference = preferences.get(report_id)
            if not preference or not preference.is_visible:
                continue
            report_config = configured.get(report_id)
            launch_mode = "generic_powerbi"
            if self.personalization_enabled:
                visual_identity = ReportVisualIdentityResolver(
                    preference,
                    category_configurations.get(preference.category),
                ).resolve().as_dict()
            else:
                fallback = ReportVisualIdentityResolver(
                    preference,
                    category_configurations.get(preference.category),
                ).resolve().as_dict()
                visual_identity = {
                    **fallback,
                    "source": "category_illustration",
                    "thumbnail_url": "",
                    "illustration_code": CATEGORY_DEFAULTS.get(preference.category, CATEGORY_DEFAULTS["other"])[0],
                }
            status = normalized_status(
                report.refresh_status,
                report.last_refresh,
                preference.freshness_threshold_hours,
            )
            cards.append({
                "id": report_id,
                "name": preference.display_name or report.display_name,
                "display_name": preference.display_name or report.display_name,
                "source_name": report.name,
                "description": preference.short_description or preference.description,
                "category": preference.category,
                "category_label": CATEGORY_LABELS.get(preference.category, "Other"),
                "tags": list(preference.tags_json or [])[:2],
                "business_owner": preference.business_owner,
                "thumbnail_url": visual_identity["thumbnail_url"],
                "thumbnail_status": preference.thumbnail_status,
                "featured": preference.featured,
                "card_badge": preference.card_badge,
                "visual_identity": visual_identity,
                "illustration_code": visual_identity["illustration_code"],
                "icon_code": visual_identity["icon_code"],
                "accent_code": visual_identity["accent"],
                "status": status,
                "raw_status": report.refresh_status,
                "refresh_status": report.refresh_status,
                "last_refresh": report.last_refresh,
                "dataset_id": report.dataset_id,
                "web_url": report.web_url,
                "launch_mode": launch_mode,
                "launch_label": "Open report",
                "launch_url": reverse("reporting-report-launch", args=[report_id]),
                "refresh_url": reverse("reporting-report-refresh-api", args=[report_id]),
                "is_favorite": report_id in favorite_ids,
                "favorite_url": reverse("reporting-report-favorite-api", args=[report_id]),
                "visual_class": preference.category.replace("_", "-"),
                "search_text": " ".join([
                    preference.display_name,
                    preference.description,
                    CATEGORY_LABELS.get(preference.category, "Other"),
                    " ".join(preference.tags_json or []),
                    preference.business_owner,
                ]).casefold(),
            })

        all_cards = list(cards)
        query = str(params.get("q") or "").strip().casefold()
        status_filter = str(params.get("status") or "all").strip().casefold()
        category = str(params.get("category") or "all").strip().casefold()
        favorites_only = str(params.get("favorites") or "").casefold() in {"1", "true", "yes"}
        if query:
            cards = [item for item in cards if all(term in item["search_text"] for term in query.split())]
        if status_filter not in {"", "all"}:
            cards = [item for item in cards if item["status"]["code"] == status_filter]
        if category not in {"", "all"}:
            cards = [item for item in cards if item["category"] == category]
        if favorites_only:
            cards = [item for item in cards if item["is_favorite"]]

        ordering = str(params.get("sort") or "alphabetical")
        if ordering == "alphabetical_desc":
            cards.sort(key=lambda item: item["name"].casefold(), reverse=True)
        elif ordering == "status":
            cards.sort(key=lambda item: (item["status"]["code"], item["name"].casefold()))
        elif ordering == "recently_refreshed":
            cards.sort(key=lambda item: item["last_refresh"] or "", reverse=True)
        else:
            cards.sort(key=lambda item: item["name"].casefold())

        summary = {code: 0 for code in ("healthy", "refreshing", "failed", "no_refresh", "stale")}
        for item in all_cards:
            summary[item["status"]["code"]] += 1
        summary["total"] = len(all_cards)

        categories = []
        for code, label in ReportingReportPreference.CATEGORIES:
            count = sum(1 for item in all_cards if item["category"] == code)
            if count:
                categories.append({"code": code, "label": label, "count": count})

        card_by_id = {item["id"]: item for item in all_cards}
        recent = []
        seen = set()
        activities = UserReportActivity.objects.filter(
            user=self.user,
            report__report_id__in=card_by_id,
            report__is_visible=True,
        ).select_related("report").order_by("-opened_at")[:40]
        for activity in activities:
            report_id = activity.report.report_id
            if report_id in seen or report_id in favorite_ids:
                continue
            seen.add(report_id)
            recent.append({**card_by_id[report_id], "opened_at": activity.opened_at})
            if len(recent) == 4:
                break

        return {
            "summary": summary,
            "categories": categories,
            "reports": cards,
            "all_reports": all_cards,
            "favorites": [item for item in all_cards if item["is_favorite"]][:4],
            "recent": recent,
            "filters": {
                "q": query,
                "status": status_filter or "all",
                "category": category or "all",
                "favorites": favorites_only,
                "sort": ordering,
            },
            "last_synchronized_at": timezone.now(),
        }
