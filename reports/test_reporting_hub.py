from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import PlatformUser, ReportingReportPreference, UserReportActivity, UserReportFavorite
from .powerbi import PowerBIReport
from .reporting_hub_service import ReportingHubService, normalized_status


class ReportingHubTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("hub-user", password="secret")
        PlatformUser.objects.create(
            django_user=self.user,
            azure_ad_id="hub-user-object",
            user_principal_name="hub-user@example.com",
            display_name="Hub User",
            can_access_reporting=True,
        )
        self.client.force_login(self.user)
        self.report_id = str(uuid4())
        self.report = PowerBIReport(
            self.report_id,
            "Fleet Performance Report",
            "Fleet Performance Report",
            "dataset-id",
            "https://app.powerbi.com/report",
            "https://app.powerbi.com/reportEmbed",
            "PowerBIReport",
            timezone.localtime().strftime("%Y-%m-%d %I:%M %p"),
            "Completed",
        )

    @patch("reports.views.list_workspace_reports_with_refresh")
    def test_premium_page_renders_catalog_and_business_status(self, list_reports):
        list_reports.return_value = [self.report]

        response = self.client.get(reverse("reporting"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "reports/home_premium.html")
        self.assertContains(response, "Reporting Hub")
        self.assertContains(response, "Healthy")
        self.assertContains(response, "Open report")
        self.assertContains(response, "Refresh report data")
        self.assertContains(response, 'data-launch-url=')
        self.assertContains(response, "report-identity-art")
        self.assertNotContains(response, "Open in Power BI")
        self.assertNotContains(response, self.report.web_url)

    @override_settings(ENABLE_PREMIUM_REPORTING_HUB="Disabled")
    @patch("reports.views.list_workspace_reports_with_refresh")
    def test_feature_flag_preserves_legacy_reporting_page(self, list_reports):
        list_reports.return_value = [self.report]

        response = self.client.get(reverse("reporting"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "reports/home.html")
        self.assertNotContains(response, self.report.web_url)

    def test_default_catalog_metadata_is_created_for_workspace_report(self):
        hub = ReportingHubService(self.user, [self.report]).build()

        preference = ReportingReportPreference.objects.get(report_id=self.report_id)
        self.assertEqual(preference.category, "fleet_performance")
        self.assertIn("availability", preference.description.lower())
        self.assertEqual(preference.illustration_code, "fleet_performance")
        self.assertEqual(preference.accent_code, "emerald")
        self.assertEqual(hub["reports"][0]["status"]["code"], "healthy")
        self.assertEqual(hub["reports"][0]["visual_identity"]["source"], "report_illustration")

    @patch("reports.views.list_workspace_reports_with_refresh")
    def test_hub_api_filters_search_without_exposing_other_results(self, list_reports):
        other = PowerBIReport(
            str(uuid4()), "Fuel Monitoring", "Fuel Monitoring", "fuel-dataset",
            "https://app.powerbi.com/fuel", "https://app.powerbi.com/fuelEmbed",
            "PowerBIReport", "", "Failed",
        )
        list_reports.return_value = [self.report, other]

        response = self.client.get(reverse("reporting-hub-api"), {"q": "fuel"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["reports"][0]["name"], "Fuel Monitoring")
        self.assertEqual(len(payload["reports"]), 1)

    @patch("reports.views.list_workspace_reports", autospec=True)
    def test_favorite_is_idempotent_and_owned_by_current_user(self, list_reports):
        list_reports.return_value = [self.report]
        url = reverse("reporting-report-favorite-api", args=[self.report_id])

        first = self.client.post(url)
        second = self.client.post(url)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(UserReportFavorite.objects.filter(user=self.user).count(), 1)
        self.assertTrue(first.json()["is_favorite"])

        removed = self.client.delete(url)
        self.assertEqual(removed.status_code, 200)
        self.assertFalse(removed.json()["is_favorite"])
        self.assertFalse(UserReportFavorite.objects.filter(user=self.user).exists())

    @patch("reports.views.list_workspace_reports")
    def test_launch_records_recent_activity_and_uses_generic_viewer(self, list_reports):
        list_reports.return_value = [self.report]

        response = self.client.get(reverse("reporting-report-launch", args=[self.report_id]))

        self.assertRedirects(
            response,
            reverse("report-detail", args=[self.report_id]),
            fetch_redirect_response=False,
        )
        activity = UserReportActivity.objects.get(user=self.user)
        self.assertEqual(activity.report.report_id, self.report_id)
        self.assertEqual(activity.source, "reporting_hub")

    def test_normalized_status_supports_refreshing_failed_no_refresh_and_stale(self):
        self.assertEqual(normalized_status("Unknown", "", None)["code"], "refreshing")
        self.assertEqual(normalized_status("Failed", "", None)["code"], "failed")
        self.assertEqual(normalized_status("Unavailable", "", None)["code"], "no_refresh")
        old = (timezone.localtime() - timedelta(days=3)).strftime("%Y-%m-%d %I:%M %p")
        self.assertEqual(normalized_status("Completed", old, 24)["code"], "stale")
