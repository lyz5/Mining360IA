import uuid
import json
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import AIConfigSection, PowerBIReport, ReportingReportPreference


def workspace_report(name: str):
    return SimpleNamespace(
        id=uuid.uuid4(),
        name=name,
        display_name=name,
        dataset_id="dataset-id",
        web_url="https://app.powerbi.com/report",
        embed_url="https://app.powerbi.com/embed",
        report_type="PowerBIReport",
        last_refresh="27 Jul 2026, 08:00",
        refresh_status="Completed",
    )


class ReportingConfigurationTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="reporting-admin",
            email="reporting-admin@example.com",
            password="password",
        )
        self.user = User.objects.create_user(username="reporting-user", password="password")
        self.first_report = workspace_report("Fleet Performance Report")
        self.second_report = workspace_report("Mine Monthly Report New")
        self.section = AIConfigSection.objects.create(code="reporting-tests", name="Reporting Tests")

    def configure_report(self, report, **overrides):
        values = {
            "section": self.section,
            "workspace_id": "workspace-id",
            "report_id": str(report.id),
            "report_name": report.name,
            "display_name": report.display_name,
            "semantic_model_id": report.dataset_id,
            "embed_url": report.embed_url,
            "validation_status": "Validated",
            "is_active": True,
        }
        values.update(overrides)
        return PowerBIReport.objects.create(**values)

    def test_reporting_configuration_requires_administrator(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("reporting-config-home"))
        self.assertEqual(response.status_code, 403)

    @patch("reports.reporting_config_views.list_workspace_reports_with_refresh")
    def test_administrator_can_save_report_visibility(self, list_reports):
        list_reports.return_value = [self.first_report, self.second_report]
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("reporting-config-home"),
            {"visible_report_ids": [str(self.first_report.id)]},
        )

        self.assertRedirects(response, reverse("reporting-config-home"))
        self.assertTrue(
            ReportingReportPreference.objects.get(report_id=str(self.first_report.id)).is_visible
        )
        self.assertFalse(
            ReportingReportPreference.objects.get(report_id=str(self.second_report.id)).is_visible
        )

    @patch("reports.reporting_config_views.list_workspace_reports_with_refresh")
    def test_visibility_save_preserves_custom_display_name(self, list_reports):
        list_reports.return_value = [self.first_report]
        ReportingReportPreference.objects.create(
            report_id=str(self.first_report.id),
            report_name=self.first_report.name,
            display_name="Fleet overview",
            is_visible=True,
        )
        self.client.force_login(self.admin)

        self.client.post(
            reverse("reporting-config-home"),
            {"visible_report_ids": [str(self.first_report.id)]},
        )

        preference = ReportingReportPreference.objects.get(report_id=str(self.first_report.id))
        self.assertEqual(preference.display_name, "Fleet overview")

    @patch("reports.reporting_config_views.list_workspace_reports_with_refresh")
    def test_configuration_displays_powerbi_and_custom_names(self, list_reports):
        list_reports.return_value = [self.first_report]
        ReportingReportPreference.objects.create(
            report_id=str(self.first_report.id),
            report_name=self.first_report.name,
            display_name="Fleet overview",
            is_visible=True,
        )
        self.client.force_login(self.admin)

        response = self.client.get(reverse("reporting-config-home"))

        self.assertContains(response, "Fleet Performance Report")
        self.assertContains(response, "Fleet overview")
        self.assertContains(response, "Mining 360 display name")

    @patch("reports.reporting_config_views.list_workspace_reports")
    def test_administrator_can_update_display_name_with_ajax(self, list_reports):
        list_reports.return_value = [self.first_report]
        self.client.force_login(self.admin)

        response = self.client.patch(
            reverse("reporting-config-display-name-api", args=[self.first_report.id]),
            data=json.dumps({"display_name": "  Fleet   Operations  "}),
            content_type="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["report"]["display_name"], "Fleet Operations")
        preference = ReportingReportPreference.objects.get(report_id=str(self.first_report.id))
        self.assertEqual(preference.report_name, self.first_report.name)
        self.assertEqual(preference.display_name, "Fleet Operations")

    @patch("reports.reporting_config_views.list_workspace_reports")
    def test_display_name_ajax_rejects_empty_name(self, list_reports):
        list_reports.return_value = [self.first_report]
        self.client.force_login(self.admin)

        response = self.client.patch(
            reverse("reporting-config-display-name-api", args=[self.first_report.id]),
            data=json.dumps({"display_name": "   "}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)

    def test_display_name_ajax_requires_administrator(self):
        self.client.force_login(self.user)

        response = self.client.patch(
            reverse("reporting-config-display-name-api", args=[self.first_report.id]),
            data=json.dumps({"display_name": "Fleet Operations"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)

    @patch("reports.views.list_workspace_reports_with_refresh")
    def test_hidden_report_is_removed_from_reporting_gallery(self, list_reports):
        list_reports.return_value = [self.first_report, self.second_report]
        self.client.force_login(self.admin)
        ReportingReportPreference.objects.create(
            report_id=str(self.second_report.id),
            report_name=self.second_report.name,
            display_name=self.second_report.display_name,
            is_visible=False,
        )

        response = self.client.get(reverse("reporting"))

        self.assertEqual(response.status_code, 200)
        reports = response.context["reports"]
        self.assertEqual([report["display_name"] for report in reports], [self.first_report.display_name])

    @patch("reports.views.list_workspace_reports_with_refresh")
    def test_custom_display_name_is_used_in_reporting_gallery(self, list_reports):
        list_reports.return_value = [self.first_report]
        self.client.force_login(self.admin)
        ReportingReportPreference.objects.create(
            report_id=str(self.first_report.id),
            report_name=self.first_report.name,
            display_name="Fleet Operations",
            is_visible=True,
        )

        response = self.client.get(reverse("reporting"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["reports"][0]["display_name"], "Fleet Operations")

    @patch("reports.views.list_workspace_reports")
    def test_hidden_report_is_removed_from_report_viewer_dropdown(
        self,
        list_reports,
    ):
        list_reports.return_value = [self.first_report, self.second_report]
        self.configure_report(self.first_report)
        self.client.force_login(self.admin)
        ReportingReportPreference.objects.create(
            report_id=str(self.second_report.id),
            report_name=self.second_report.name,
            display_name=self.second_report.display_name,
            is_visible=False,
        )

        response = self.client.get(reverse("report-detail", args=[self.first_report.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [str(report.id) for report in response.context["reports"]],
            [str(self.first_report.id)],
        )
        self.assertContains(response, reverse("powerbi-interaction-embed-config", args=[self.first_report.id]))
        self.assertContains(response, 'id="powerbi-report"')

    @patch("reports.views.list_workspace_reports")
    def test_custom_display_name_is_used_in_report_viewer(self, list_reports):
        list_reports.return_value = [self.first_report]
        self.configure_report(self.first_report)
        ReportingReportPreference.objects.create(
            report_id=str(self.first_report.id),
            report_name=self.first_report.name,
            display_name="Fleet Operations",
            is_visible=True,
        )
        self.client.force_login(self.admin)

        response = self.client.get(reverse("report-detail", args=[self.first_report.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["report"].display_name, "Fleet Operations")

    @patch("reports.views.list_workspace_reports")
    def test_prime_movers_power_apps_report_uses_delegated_loader(
        self,
        list_reports,
    ):
        original = workspace_report("Prime Movers Operational Status")
        original.id = uuid.UUID("7965812a-e2d7-4950-9651-a148d8fdd235")
        list_reports.return_value = [original]
        self.configure_report(
            original,
            authentication_mode="user_owns_data",
            contains_powerapps_visual=True,
            requires_user_identity=True,
        )
        self.client.force_login(self.admin)

        response = self.client.get(reverse("report-detail", args=[original.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="powerbi-report"')
        self.assertContains(response, "Corporate Microsoft account required")
        self.assertContains(response, reverse("powerbi-interaction-embed-config", args=[original.id]))
        self.assertNotContains(response, 'id="powerbi-secure-report"')
        self.assertNotContains(response, "autoAuth=true")
