import uuid
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import ReportingReportPreference


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

    @patch("reports.views.generate_report_embed_token", return_value="embed-token")
    @patch("reports.views.list_workspace_reports")
    def test_hidden_report_is_removed_from_report_viewer_dropdown(
        self,
        list_reports,
        generate_embed_token,
    ):
        list_reports.return_value = [self.first_report, self.second_report]
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
        generate_embed_token.assert_called_once_with(self.first_report, ["Global"])
