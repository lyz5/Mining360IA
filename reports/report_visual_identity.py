from __future__ import annotations

from dataclasses import asdict, dataclass

from django.urls import reverse

from .models import ReportCategory, ReportingReportPreference


ACCENT_TOKENS = {code for code, _label in ReportingReportPreference.ACCENTS}
ICON_CODES = {
    "activity", "calculator", "calendar", "chart", "dashboard", "droplet",
    "engine", "flask", "gauge", "hard-hat", "package", "signal", "truck", "users",
}
ILLUSTRATION_CODES = {
    "connectivity", "customer_performance", "fleet_performance", "fuel_monitoring",
    "generic_analytics", "lifecycle_cost", "logistics", "monthly_report",
    "monthly_report_customer", "monthly_report_internal", "operator_induced",
    "parts_aftermarket", "prime_movers", "prime_movers_v3", "sos_analysis",
}

CATEGORY_DEFAULTS = {
    "fleet_performance": ("fleet_performance", "activity", "emerald"),
    "maintenance_reliability": ("sos_analysis", "flask", "purple"),
    "operations": ("logistics", "truck", "amber"),
    "fuel_connectivity": ("connectivity", "signal", "blue"),
    "parts_aftermarket": ("parts_aftermarket", "package", "rose"),
    "management_reports": ("monthly_report", "calendar", "slate"),
    "lifecycle_cost": ("lifecycle_cost", "calculator", "cyan"),
    "customer_performance": ("customer_performance", "users", "blue"),
    "other": ("generic_analytics", "chart", "yellow"),
}


@dataclass(frozen=True)
class ResolvedReportVisualIdentity:
    source: str
    thumbnail_url: str
    illustration_code: str
    icon_code: str
    accent: str
    background_token: str
    badge: str
    status: str
    focal_x: int
    focal_y: int

    def as_dict(self):
        return asdict(self)


class ReportVisualIdentityResolver:
    def __init__(self, preference: ReportingReportPreference, category: ReportCategory | None = None):
        self.preference = preference
        self.category = category

    def resolve(self) -> ResolvedReportVisualIdentity:
        preference = self.preference
        category = self.category
        if category is None:
            category = ReportCategory.objects.filter(code=preference.category, active=True).first()
        fallback_illustration, fallback_icon, fallback_accent = CATEGORY_DEFAULTS.get(
            preference.category,
            CATEGORY_DEFAULTS["other"],
        )
        category_illustration = (
            category.illustration_code if category and category.illustration_code in ILLUSTRATION_CODES
            else fallback_illustration
        )
        icon = preference.icon_code if preference.icon_code in ICON_CODES else (
            category.icon_code if category and category.icon_code in ICON_CODES else fallback_icon
        )
        accent = preference.accent_code if preference.accent_code in ACCENT_TOKENS else (
            category.accent_code if category and category.accent_code in ACCENT_TOKENS else fallback_accent
        )
        source = "generic_fallback"
        thumbnail_url = ""
        illustration = "generic_analytics"
        requested_source = preference.thumbnail_source or "automatic"
        manual_url = ""
        selected_asset = preference.selected_visual_asset
        if (
            selected_asset
            and selected_asset.active
            and selected_asset.validation_status == "Validated"
            and self._stored_file_exists(selected_asset.file)
        ):
            manual_url = reverse("reporting-visual-asset-file", args=[selected_asset.id])
        elif preference.thumbnail and self._stored_file_exists(preference.thumbnail):
            manual_url = reverse("reporting-report-thumbnail", args=[preference.report_id])
        elif preference.thumbnail_url and preference.thumbnail_status in {"configured", "ready"}:
            manual_url = preference.thumbnail_url
        candidates = {
            "manual_thumbnail": (manual_url, "") if manual_url else None,
            "powerbi_screenshot": (preference.powerbi_screenshot_url, "") if preference.powerbi_screenshot_url and preference.thumbnail_status in {"configured", "ready"} else None,
            "report_illustration": ("", preference.illustration_code) if preference.illustration_code in ILLUSTRATION_CODES else None,
            "category_illustration": ("", category_illustration) if category_illustration in ILLUSTRATION_CODES and preference.category != "other" else None,
            "category_icon": ("", "") if icon in ICON_CODES and (preference.category != "other" or bool(preference.icon_code)) else None,
        }
        priority = ["manual_thumbnail", "powerbi_screenshot", "report_illustration", "category_illustration", "category_icon"]
        if requested_source != "automatic" and requested_source in priority:
            priority = [requested_source, *[item for item in priority if item != requested_source]]
        for candidate_source in priority:
            candidate = candidates[candidate_source]
            if candidate is None:
                continue
            source = candidate_source
            thumbnail_url, illustration = candidate
            break

        status = self._status(source, thumbnail_url, illustration, icon)
        return ResolvedReportVisualIdentity(
            source=source,
            thumbnail_url=thumbnail_url,
            illustration_code=illustration,
            icon_code=icon,
            accent=accent,
            background_token=f"{accent}_soft",
            badge=preference.card_badge,
            status=status,
            focal_x=max(0, min(100, preference.thumbnail_focal_x)),
            focal_y=max(0, min(100, preference.thumbnail_focal_y)),
        )

    @staticmethod
    def _stored_file_exists(field_file):
        try:
            return bool(field_file.name and field_file.storage.exists(field_file.name))
        except (OSError, ValueError):
            return False

    def _status(self, source, thumbnail_url, illustration, icon):
        if self.preference.thumbnail_status == "failed":
            return "invalid"
        has_metadata = bool(
            self.preference.display_name
            and (self.preference.short_description or self.preference.description)
            and self.preference.category != "other"
        )
        has_report_visual = source in {"manual_thumbnail", "powerbi_screenshot", "report_illustration"}
        if has_metadata and has_report_visual and icon:
            return "complete" if self.preference.validation_status == "Validated" else "needs_review"
        if has_metadata and (thumbnail_url or illustration or icon):
            return "partial"
        if source in {"category_illustration", "category_icon", "generic_fallback"}:
            return "default"
        return "invalid"


def resolved_visual_identity(preference):
    return ReportVisualIdentityResolver(preference).resolve().as_dict()
