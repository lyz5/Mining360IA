from __future__ import annotations

from datetime import date

from django.urls import reverse

from .access_control import is_platform_admin
from .models import PowerBIReport, ReportingReportPreference, UserReportActivity, UserReportFavorite
from .reporting_hub_service import CATEGORY_LABELS, normalized_status


PERIOD_LABELS = dict(PowerBIReport.VIEWER_PERIODS)
DEFAULT_PERIODS = ["ytd", "last_12_months", "custom"]


def _runtime_id(report):
    return str(getattr(report, "id", "") or "")


def _query_values(query, code, multiple=False):
    values = query.getlist(code) if multiple and hasattr(query, "getlist") else [query.get(code)]
    return [str(value).strip() for value in values if str(value or "").strip()]


def _date_value(value):
    try:
        return date.fromisoformat(str(value or "")).isoformat()
    except ValueError:
        return ""


class ReportViewerConfigurationService:
    def __init__(self, user, configured, runtime_reports, query):
        self.user = user
        self.configured = configured
        self.runtime_reports = list(runtime_reports)
        self.query = query

    def _preference(self):
        return ReportingReportPreference.objects.filter(report_id=self.configured.report_id).first()

    def _runtime(self):
        return next((item for item in self.runtime_reports if _runtime_id(item) == self.configured.report_id), None)

    def _periods(self):
        values = self.configured.viewer_available_periods or DEFAULT_PERIODS
        values = [value for value in values if value in PERIOD_LABELS]
        if not self.configured.viewer_custom_range_enabled:
            values = [value for value in values if value != "custom"]
        return values or ["ytd"]

    def _pages(self):
        pages = list(self.configured.pages.filter(is_active=True).order_by("page_order", "page_display_name"))
        return [{
            "internal_name": item.page_internal_name,
            "display_name": item.page_display_name,
            "is_default": item.is_default or item.page_internal_name == self.configured.default_page_internal_name,
        } for item in pages]

    def _initial_context(self, periods, pages):
        requested_period = str(self.query.get("period") or self.configured.viewer_default_period)
        period = requested_period if requested_period in periods else self.configured.viewer_default_period
        if period not in periods:
            period = periods[0]
        start_date = _date_value(self.query.get("start_date")) if period == "custom" else ""
        end_date = _date_value(self.query.get("end_date")) if period == "custom" else ""
        filters = []
        chips = []
        for parameter in self.configured.context_parameters.filter(active=True):
            if parameter.code in {"period", "start_date", "end_date", "page"}:
                continue
            values = _query_values(self.query, parameter.code, parameter.supports_multiple_values)
            if not values or not parameter.powerbi_table or not parameter.powerbi_column:
                continue
            filters.append({
                "filter_code": parameter.code,
                "display_name": parameter.display_name,
                "table": parameter.powerbi_table,
                "column": parameter.powerbi_column,
                "operator": parameter.operator or "In",
                "values": values,
                "filter_type": "basic",
                "slicer_internal_name": "",
            })
            chips.append({"code": parameter.code, "label": parameter.display_name, "value": ", ".join(values)})
        requested_page = str(self.query.get("page") or "").strip()
        allowed_pages = {item["internal_name"] for item in pages}
        page = requested_page if requested_page in allowed_pages else ""
        return {
            "period": period,
            "start_date": start_date,
            "end_date": end_date,
            "page": page,
            "filters": filters,
            "chips": chips,
        }

    def _switcher(self):
        configured = {
            item.report_id: item
            for item in PowerBIReport.objects.filter(is_active=True, launch_mode="generic_powerbi")
        }
        report_ids = list(configured)
        preferences = {
            item.report_id: item
            for item in ReportingReportPreference.objects.filter(report_id__in=report_ids, is_visible=True)
        }
        favorites = set(UserReportFavorite.objects.filter(
            user=self.user, report__report_id__in=report_ids,
        ).values_list("report__report_id", flat=True))
        recent_ids = list(UserReportActivity.objects.filter(
            user=self.user, report__report_id__in=report_ids,
        ).values_list("report__report_id", flat=True)[:20])
        recent_rank = {report_id: index for index, report_id in enumerate(dict.fromkeys(recent_ids))}
        items = []
        for report_id, report_config in configured.items():
            preference = preferences.get(report_id)
            if not preference or not report_config:
                continue
            items.append({
                "id": report_id,
                "display_name": preference.display_name or getattr(runtime, "display_name", ""),
                "category": preference.category,
                "category_label": CATEGORY_LABELS.get(preference.category, "Other"),
                "status": {"code": "neutral", "label": "Available", "detail": "Open in Mining 360"},
                "favorite": report_id in favorites,
                "recent": report_id in recent_rank,
                "recent_rank": recent_rank.get(report_id, 9999),
                "url": reverse("report-detail", args=[report_id]),
            })
        return sorted(items, key=lambda item: (item["display_name"].casefold(), item["id"]))

    def build(self):
        preference = self._preference()
        runtime = self._runtime()
        periods = self._periods()
        pages = self._pages()
        status = normalized_status(
            getattr(runtime, "refresh_status", ""),
            getattr(runtime, "last_refresh", ""),
            preference.freshness_threshold_hours if preference else None,
        ) if runtime else {
            "code": "neutral",
            "label": "Report ready",
            "detail": "Refresh status loading",
        }
        admin = is_platform_admin(self.user)
        powerbi_url = getattr(runtime, "web_url", "") or (
            f"https://app.powerbi.com/groups/{self.configured.workspace_id}/reports/{self.configured.report_id}"
            if self.configured.workspace_id and self.configured.report_id else ""
        )
        return {
            "report": {
                "id": self.configured.report_id,
                "display_name": (preference.display_name if preference else "") or self.configured.display_name,
                "source_name": self.configured.report_name,
                "launch_mode": self.configured.launch_mode,
                "category": preference.category if preference else "other",
                "category_label": CATEGORY_LABELS.get(preference.category if preference else "other", "Other"),
            },
            "viewer": {
                "show_filter_bar": self.configured.viewer_show_filter_bar and self.configured.supports_embedded_filtering,
                "default_period": self.configured.viewer_default_period,
                "available_periods": [{"code": code, "label": PERIOD_LABELS[code]} for code in periods],
                "auto_apply_presets": self.configured.viewer_auto_apply_presets,
                "custom_range_enabled": self.configured.viewer_custom_range_enabled,
                "default_page": self.configured.default_page_internal_name,
                "show_page_navigation": self.configured.viewer_external_page_navigation,
                "default_fit_mode": self.configured.display_option,
                "focus_mode_enabled": self.configured.viewer_focus_mode_enabled,
                "fullscreen_enabled": self.configured.viewer_fullscreen_enabled,
                "reset_behavior": self.configured.viewer_reset_behavior,
                "date_mapping": {
                    "table": self.configured.viewer_date_table,
                    "column": self.configured.viewer_date_column,
                } if self.configured.viewer_date_table and self.configured.viewer_date_column else None,
                "help_text": self.configured.viewer_help_text,
            },
            "pages": pages,
            "filter_mappings": [{
                "code": item.code,
                "display_name": item.display_name,
                "source": item.source,
                "data_type": item.data_type,
                "required": item.required,
            } for item in self.configured.context_parameters.filter(active=True)],
            "initial_context": self._initial_context(periods, pages),
            "refresh_status": status,
            "switcher": self._switcher(),
            "permissions": {
                "allow_focus": self.configured.viewer_focus_mode_enabled,
                "allow_fullscreen": self.configured.viewer_fullscreen_enabled,
                "allow_open_powerbi": bool(admin and self.configured.viewer_allow_open_powerbi and powerbi_url),
                "open_powerbi_url": powerbi_url if admin and self.configured.viewer_allow_open_powerbi else "",
                "show_technical_details": admin,
            },
        }
