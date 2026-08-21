from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .models import DataBrowser


class DataBrowserResilienceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="data-user",
            email="data-user@example.com",
            password="test-password",
        )
        self.client.force_login(self.user)
        self.browser = DataBrowser.objects.create(
            name="Reliability browser",
            table_name="ReliabilityBrowser",
            source_view_name="dbo.ReliabilityBrowser",
        )

    @patch("reports.views.preview_browser_data", side_effect=RuntimeError("secret database detail"))
    def test_preview_hides_database_connection_details(self, _preview):
        response = self.client.get(reverse("data-browser-data-api", args=[self.browser.id]))

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error_code"], "data_source_unavailable")
        self.assertNotContains(response, "secret database detail", status_code=503)

    @patch("reports.views.preview_browser_data", side_effect=RuntimeError("secret database detail"))
    def test_export_hides_database_connection_details(self, _preview):
        response = self.client.get(reverse("data-browser-export-api", args=[self.browser.id]))

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error_code"], "data_source_unavailable")
        self.assertNotContains(response, "secret database detail", status_code=503)

    def test_data_home_avoids_mapping_n_plus_one_and_defers_columns(self):
        DataBrowser.objects.bulk_create([
            DataBrowser(
                name=f"Browser {index}",
                table_name=f"Browser{index}",
                source_view_name=f"dbo.Browser{index}",
            )
            for index in range(4)
        ])
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("data-home"))

        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(queries), 5)
        browser_state = response.context["browser_state"]
        self.assertTrue(browser_state)
        self.assertTrue(all("columns" not in item for item in browser_state))
