import uuid
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from .models import (
    AIConfigSection,
    PlatformUser,
    PowerBIReport,
    ReportContextParameter,
    ReportingReportPreference,
)
from .report_viewer_service import ReportViewerConfigurationService
from .reporting_configuration_service import save_configuration


def runtime_report(report_id, name="Fleet Performance Report"):
    return SimpleNamespace(
        id=uuid.UUID(str(report_id)),
        name=name,
        display_name=name,
        dataset_id="dataset-id",
        web_url="https://app.powerbi.com/groups/workspace/reports/report",
        embed_url="https://app.powerbi.com/reportEmbed?reportId=report",
        refresh_status="Completed",
        last_refresh="22 Aug 2026, 07:40",
    )


@override_settings(ENABLE_PREMIUM_GENERIC_REPORT_VIEWER="Production")
class PremiumReportViewerTests(TestCase):
    def setUp(self):
        self.report_id = uuid.uuid4()
        self.section = AIConfigSection.objects.create(code="viewer-tests", name="Viewer Tests")
        self.configured = PowerBIReport.objects.create(
            section=self.section,
            workspace_id="workspace-id",
            report_id=str(self.report_id),
            report_name="Fleet Performance Report",
            display_name="Fleet Performance Report",
            semantic_model_id="dataset-id",
            embed_url="https://app.powerbi.com/reportEmbed?reportId=report",
            validation_status="Validated",
            viewer_external_page_navigation=True,
            viewer_allow_open_powerbi=True,
        )
        self.preference = ReportingReportPreference.objects.create(
            report_id=str(self.report_id),
            report_name=self.configured.report_name,
            display_name=self.configured.display_name,
            description="Monitor fleet performance.",
            category="fleet_performance",
            is_visible=True,
        )
        self.admin = User.objects.create_superuser("viewer-admin", "admin@example.com", "password")
        self.user = User.objects.create_user("viewer-user", password="password")
        PlatformUser.objects.create(
            django_user=self.user,
            azure_ad_id="viewer-user-object",
            user_principal_name="viewer.user@example.com",
            display_name="Viewer User",
            can_access_reporting=True,
        )
        self.runtime = runtime_report(self.report_id)

    def test_only_configured_context_parameters_become_powerbi_filters(self):
        ReportContextParameter.objects.create(
            report=self.configured,
            code="minesite",
            display_name="Mine Site",
            source="query_string",
            powerbi_table="MineSiteList_MiningProd",
            powerbi_column="MineSite",
            active=True,
        )
        query = self.client.get("/?minesite=Essakane&table=Secret&column=Hidden").wsgi_request.GET
        payload = ReportViewerConfigurationService(self.user, self.configured, [self.runtime], query).build()

        self.assertEqual(payload["initial_context"]["filters"], [{
            "filter_code": "minesite",
            "display_name": "Mine Site",
            "table": "MineSiteList_MiningProd",
            "column": "MineSite",
            "operator": "In",
            "values": ["Essakane"],
            "filter_type": "basic",
            "slicer_internal_name": "",
        }])
        self.assertNotIn("Secret", str(payload))

    def test_open_powerbi_service_is_admin_only(self):
        query = self.client.get("/").wsgi_request.GET
        standard = ReportViewerConfigurationService(self.user, self.configured, [self.runtime], query).build()
        admin = ReportViewerConfigurationService(self.admin, self.configured, [self.runtime], query).build()

        self.assertFalse(standard["permissions"]["allow_open_powerbi"])
        self.assertTrue(admin["permissions"]["allow_open_powerbi"])
        self.assertEqual(admin["permissions"]["open_powerbi_url"], self.runtime.web_url)

    @patch("reports.powerbi.list_workspace_reports_with_refresh")
    def test_viewer_configuration_endpoint_preserves_url_context(self, powerbi_reports):
        ReportContextParameter.objects.create(
            report=self.configured, code="model", display_name="Model", source="homepage",
            powerbi_table="EquipmentList_MiningProd", powerbi_column="Model", active=True,
        )
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("report-viewer-configuration-api", args=[self.report_id]),
            {"period": "last_12_months", "model": "777", "page": "not-approved"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["initial_context"]["period"], "last_12_months")
        self.assertEqual(data["initial_context"]["filters"][0]["values"], ["777"])
        self.assertEqual(data["initial_context"]["page"], "")
        self.assertEqual(data["refresh_status"]["code"], "neutral")
        self.assertEqual(data["switcher"], [])
        self.assertIn("viewer_config;dur=", response.headers["Server-Timing"])
        powerbi_reports.assert_not_called()

    def test_report_switcher_is_loaded_from_dedicated_endpoint(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("report-viewer-switcher-api", args=[self.report_id]),
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["switcher"]), 1)
        self.assertEqual(data["switcher"][0]["display_name"], "Fleet Performance Report")
        self.assertIn("viewer_switcher;dur=", response.headers["Server-Timing"])

    @patch("reports.views.list_workspace_reports")
    def test_generic_report_uses_premium_workspace_shell(self, reports):
        reports.return_value = [self.runtime]
        self.client.force_login(self.user)
        response = self.client.get(reverse("report-detail", args=[self.report_id]))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "reports/detail_premium.html")
        self.assertContains(response, "data-report-viewer")
        self.assertContains(response, "data-switcher-open")
        self.assertContains(response, "data-viewer-switcher-url")
        self.assertContains(response, "data-embed-url")
        self.assertContains(response, "data-canvas-workspace")
        content = response.content.decode("utf-8")
        toolbar_start = content.index('class="report-canvas-toolbar"')
        filter_bar = content.index("data-command-bar")
        canvas_stage = content.index('class="report-canvas-stage"')
        self.assertLess(toolbar_start, filter_bar)
        self.assertLess(filter_bar, canvas_stage)
        self.assertEqual(content.count("data-fullscreen-toggle"), 1)
        self.assertNotContains(response, "RLS Role")
        self.assertNotContains(response, "Diagnose slicers")
        reports.assert_not_called()

    def test_viewer_configuration_is_saved_and_versioned(self):
        saved = save_configuration(self.runtime, {
            "version": self.configured.configuration_version,
            "viewer": {
                "show_filter_bar": True,
                "default_period": "last_12_months",
                "available_periods": ["ytd", "last_12_months", "custom"],
                "auto_apply_presets": True,
                "custom_range_enabled": True,
                "external_page_navigation": True,
                "focus_mode_enabled": True,
                "fullscreen_enabled": True,
                "allow_open_powerbi": False,
                "reset_behavior": "defaults",
                "date_table": "Date",
                "date_column": "Date",
                "help_text": "Use approved Mining 360 filters.",
            },
        }, self.admin)

        self.configured.refresh_from_db()
        self.assertEqual(self.configured.viewer_default_period, "last_12_months")
        self.assertEqual(saved["viewer"]["help_text"], "Use approved Mining 360 filters.")
        self.assertFalse(self.configured.viewer_allow_open_powerbi)


class PremiumReportViewerSourceTests(SimpleTestCase):
    def test_viewer_uses_viewport_layout_and_persistent_embed_api(self):
        from django.conf import settings

        css = (settings.BASE_DIR / "reports" / "static" / "reports" / "report_viewer.css").read_text(encoding="utf-8")
        script = (settings.BASE_DIR / "reports" / "static" / "reports" / "report_viewer.js").read_text(encoding="utf-8")
        self.assertIn("height: 100dvh", css)
        self.assertIn("flex: 1 1 auto", css)
        self.assertNotIn("height: 700px", css)
        self.assertIn("state.embed.applyFilters", script)
        self.assertIn("state.embed.setFitMode", script)
        self.assertIn("state.embed.bootstrap", script)
        self.assertIn("loadSwitcher()", script)
        self.assertNotIn("window.location.reload", script)

        embed_script = (settings.BASE_DIR / "reports" / "static" / "reports" / "powerbi_embed.js").read_text(encoding="utf-8")
        self.assertIn("window.powerbi.bootstrap", embed_script)
