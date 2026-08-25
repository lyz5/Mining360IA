import json
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import (
    AIConfigSection,
    PowerBIReport,
    ReportConfigurationAuditLog,
    ReportConfigurationTestRun,
    ReportConfigurationVersion,
    ReportContextParameter,
    ReportingReportPreference,
)


def workspace_report(name="Fleet Performance Report", report_id=None):
    return SimpleNamespace(
        id=report_id or uuid.uuid4(),
        name=name,
        display_name=name,
        dataset_id="dataset-id",
        web_url="https://app.powerbi.com/report",
        embed_url="https://app.powerbi.com/embed",
        report_type="PowerBIReport",
        last_refresh="22 Aug 2026, 07:40",
        refresh_status="Completed",
    )


@override_settings(ENABLE_REPORTING_CONFIGURATION_WORKSPACE="Production")
class ReportingConfigurationWorkspaceTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("config-admin", "admin@example.com", "password")
        self.user = User.objects.create_user("config-user", password="password")
        self.runtime = workspace_report()
        self.section = AIConfigSection.objects.create(code="workspace-tests", name="Workspace Tests")

    def create_configuration(self, **overrides):
        values = {
            "section": self.section,
            "workspace_id": "workspace-id",
            "report_id": str(self.runtime.id),
            "report_name": self.runtime.name,
            "display_name": self.runtime.display_name,
            "semantic_model_id": self.runtime.dataset_id,
            "embed_url": self.runtime.embed_url,
            "validation_status": "To Review",
            "is_active": True,
        }
        values.update(overrides)
        return PowerBIReport.objects.create(**values)

    def payload(self, version=1):
        return {
            "version": version,
            "general": {
                "display_name": "Fleet Performance",
                "description": "Monitor availability, reliability and downtime.",
                "category": "fleet_performance",
                "business_owner": "Fleet Performance",
                "tags": ["Availability", "Downtime"],
                "visible": True,
                "active": True,
                "featured": False,
                "display_order": 1,
                "freshness_threshold_hours": 24,
            },
            "visual_identity": {
                "short_description": "Monitor availability, reliability and downtime.",
                "long_description": "Detailed fleet-performance analytics.",
                "business_purpose": "Support fleet performance reviews.",
                "technical_owner": "Data Platform",
                "secondary_categories": [],
                "thumbnail_source": "report_illustration",
                "thumbnail_url": "",
                "powerbi_screenshot_url": "",
                "thumbnail_status": "fallback",
                "thumbnail_focal_x": 50,
                "thumbnail_focal_y": 50,
                "illustration_code": "fleet_performance",
                "icon_code": "activity",
                "accent_code": "emerald",
                "card_badge": "Featured",
                "card_style": "standard",
                "featured": True,
            },
            "launch": {
                "launch_mode": "generic_powerbi",
                "authentication_mode": "app_owns_data",
                "open_behavior": "inside_mining360",
                "contains_powerapps_visual": False,
                "requires_user_identity": False,
                "required_entra_tenant_id": "",
                "supports_chatbot_navigation": True,
                "supports_embedded_filtering": True,
            },
            "navigation": {
                "opening_profile_name": "Fleet standard",
                "default_page_internal_name": "",
                "display_option": "fit_to_page",
                "filter_pane_visible": False,
                "page_navigation_visible": True,
                "bookmarks_pane_visible": False,
                "background_type": "default",
                "default_rls_role": "Global",
            },
            "troubleshooting": {
                "enabled": True,
                "prompt": "Help diagnose {{report_name}}: {{error_message}}",
                "instructions": "Run diagnostics before escalating.",
            },
            "parameters": [{
                "code": "minesite",
                "display_name": "Mine Site",
                "source": "chatbot",
                "data_type": "text",
                "required": False,
                "default_value": "",
                "powerbi_table": "MineSite",
                "powerbi_column": "MineSite",
                "operator": "In",
                "supports_multiple_values": False,
                "active": True,
            }],
        }

    def test_page_uses_master_detail_workspace_and_keeps_legacy_rollback(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("reporting-config-home"))
        self.assertContains(response, "data-report-config-workspace")
        self.assertContains(response, "Select a report to view and edit its configuration")
        self.assertContains(response, "data-open-powerbi-service")
        self.assertContains(response, 'data-area="essentials"')
        self.assertContains(response, 'data-area="appearance"')
        self.assertContains(response, 'data-area="open_navigate"')
        self.assertContains(response, 'data-area="help_ai"')
        self.assertContains(response, 'data-area="test_history"')
        for original_section in ("general", "visual", "catalog", "launch", "viewer", "navigation", "troubleshooting", "parameters", "tests", "audit"):
            self.assertContains(response, f'data-panel="{original_section}"')
        self.assertContains(response, "Live Card Preview")
        self.assertContains(response, "Change card image")
        self.assertContains(response, "Recommended size: 1200 × 450 px")
        self.assertContains(response, "data-thumbnail-file")
        self.assertContains(response, "data-test-drawer")
        self.assertContains(response, "data-checklist-drawer")
        self.assertContains(response, "View configuration health")

        with patch("reports.reporting_config_views.list_workspace_reports_with_refresh", return_value=[]):
            legacy = self.client.get(reverse("reporting-config-home") + "?legacy=1")
        self.assertEqual(legacy.status_code, 200)
        self.assertNotContains(legacy, "data-report-config-workspace")

    @patch("reports.reporting_configuration_views.list_workspace_reports")
    def test_admin_configuration_detail_exposes_powerbi_service_url(self, list_reports):
        list_reports.return_value = [self.runtime]
        configured = self.create_configuration()
        ReportingReportPreference.objects.create(
            report_id=configured.report_id,
            report_name=configured.report_name,
            display_name=configured.display_name,
            category="fleet_performance",
        )
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("reporting-configuration-detail-api", args=[self.runtime.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["configuration"]["source"]["web_url"],
            self.runtime.web_url,
        )

    @patch("reports.reporting_configuration_views.list_workspace_reports_with_refresh")
    def test_ajax_list_search_and_summary(self, list_reports):
        list_reports.return_value = [self.runtime, workspace_report("Mine Monthly Report")]
        ReportingReportPreference.objects.create(
            report_id=str(self.runtime.id), report_name=self.runtime.name,
            display_name="Fleet Overview", category="fleet_performance", is_visible=True,
        )
        self.client.force_login(self.admin)
        response = self.client.get(reverse("reporting-configuration-list-api"), {"q": "fleet"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["display_name"], "Fleet Overview")
        self.assertEqual(data["summary"]["total"], 2)

    @patch("reports.reporting_configuration_views.list_workspace_reports")
    def test_first_save_creates_version_audit_and_parameter(self, list_reports):
        list_reports.return_value = [self.runtime]
        self.client.force_login(self.admin)
        body = self.payload(version=0)
        response = self.client.patch(
            reverse("reporting-configuration-detail-api", args=[self.runtime.id]),
            data=json.dumps(body), content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        configured = PowerBIReport.objects.get(report_id=str(self.runtime.id))
        self.assertEqual(configured.configuration_version, 2)
        self.assertEqual(configured.launch_mode, "generic_powerbi")
        self.assertEqual(configured.authentication_mode, "app_owns_data")
        self.assertEqual(configured.context_parameters.get().code, "minesite")
        preference = ReportingReportPreference.objects.get(report_id=str(self.runtime.id))
        self.assertEqual(preference.illustration_code, "fleet_performance")
        self.assertEqual(preference.accent_code, "emerald")
        self.assertTrue(preference.featured)
        self.assertTrue(ReportConfigurationVersion.objects.filter(report=configured, version=2).exists())
        self.assertTrue(ReportConfigurationAuditLog.objects.filter(report=configured, action="updated").exists())

    @patch("reports.reporting_configuration_views.list_workspace_reports")
    def test_optimistic_concurrency_rejects_stale_version(self, list_reports):
        list_reports.return_value = [self.runtime]
        configured = self.create_configuration(configuration_version=4)
        ReportingReportPreference.objects.create(
            report_id=configured.report_id, report_name=configured.report_name,
            display_name=configured.display_name, category="fleet_performance",
        )
        self.client.force_login(self.admin)
        response = self.client.patch(
            reverse("reporting-configuration-detail-api", args=[self.runtime.id]),
            data=json.dumps(self.payload(version=3)), content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error_code"], "VERSION_CONFLICT")

    @patch("reports.reporting_configuration_views.list_workspace_reports")
    def test_test_center_persists_non_destructive_result(self, list_reports):
        list_reports.return_value = [self.runtime]
        configured = self.create_configuration()
        ReportingReportPreference.objects.create(
            report_id=configured.report_id, report_name=configured.report_name,
            display_name=configured.display_name, category="fleet_performance",
        )
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("reporting-configuration-test-api", args=[self.runtime.id]),
            data="{}", content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(ReportConfigurationTestRun.objects.filter(report=configured).exists())

    def test_prompt_preview_rejects_unknown_variables(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("reporting-configuration-prompt-preview-api", args=[self.runtime.id]),
            data=json.dumps({"prompt": "Check {{report_name}} and {{secret_token}}"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["unknown_variables"], ["secret_token"])

    @patch("reports.reporting_configuration_views.list_workspace_reports")
    def test_copy_settings_preserves_target_powerbi_ids(self, list_reports):
        target_runtime = self.runtime
        source_runtime = workspace_report("Source Report")
        list_reports.return_value = [target_runtime, source_runtime]
        source = PowerBIReport.objects.create(
            section=self.section, workspace_id="source-workspace", report_id=str(source_runtime.id),
            report_name=source_runtime.name, display_name=source_runtime.name,
            semantic_model_id="source-dataset", launch_mode="generic_powerbi",
            authentication_mode="app_owns_data", display_option="fit_to_width",
            validation_status="Validated",
        )
        target = self.create_configuration(workspace_id="target-workspace", semantic_model_id="target-dataset")
        ReportingReportPreference.objects.create(
            report_id=source.report_id, report_name=source.report_name, display_name=source.display_name,
            category="fleet_performance", description="Source description",
        )
        ReportingReportPreference.objects.create(
            report_id=target.report_id, report_name=target.report_name, display_name=target.display_name,
            category="other",
        )
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("reporting-configuration-copy-api", args=[target_runtime.id]),
            data=json.dumps({"source_report_id": source.report_id, "sections": ["catalog", "launch"]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        target.refresh_from_db()
        self.assertEqual(target.workspace_id, "target-workspace")
        self.assertEqual(target.semantic_model_id, "target-dataset")
        self.assertEqual(target.report_id, str(target_runtime.id))

    def test_workspace_api_requires_admin(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("reporting-configuration-list-api"))
        self.assertEqual(response.status_code, 403)
