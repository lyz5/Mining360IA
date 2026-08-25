from unittest.mock import Mock, patch
from uuid import uuid4

from django.contrib.auth.models import User
from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from . import powerbi
from .models import PlatformUser
from .powerbi import PowerBIReport, generate_report_embed_token
from .models import PowerBIReport as ConfiguredPowerBIReport
from .powerbi_interaction_service import _report_launch_url


class PowerBIReportEmbeddingTests(SimpleTestCase):
    def setUp(self):
        powerbi._REPORT_REFRESH_CACHE.clear()
        powerbi._DATASET_LIST_CACHE.clear()
        powerbi._DATASET_METADATA_CACHE.clear()
        powerbi._LINKED_DATASET_CACHE.clear()
        powerbi._EMBED_TOKEN_CACHE.clear()
        powerbi._EMBED_TOKEN_INFLIGHT.clear()

    def test_powerbi_client_is_served_locally_in_every_embed_surface(self):
        template_root = settings.BASE_DIR / "reports" / "templates" / "reports"
        for template_name in ("detail.html", "detail_premium.html", "ai.html", "knowledge_base.html"):
            source = (template_root / template_name).read_text(encoding="utf-8")
            with self.subTest(template=template_name):
                self.assertIn("reports/vendor/powerbi-client-2.23.7.min.js", source)
                self.assertNotIn("cdn.jsdelivr.net/npm/powerbi-client", source)

    def test_all_configured_reports_use_the_generic_viewer(self):
        self.assertEqual(
            ConfiguredPowerBIReport.LAUNCH_MODES,
            [("generic_powerbi", "Generic Power BI viewer")],
        )
        configured = ConfiguredPowerBIReport(report_id=str(uuid4()))
        self.assertEqual(
            _report_launch_url(configured),
            reverse("report-detail", args=[configured.report_id]),
        )

    @patch("reports.powerbi.list_workspace_datasets")
    def test_sos_report_resolves_fpr_global_rls_dependency(self, list_datasets):
        list_datasets.return_value = [
            {
                "id": "fpr-global-dataset",
                "name": "FPR Global DB + RLS",
            },
        ]

        dataset_ids = powerbi.get_report_hint_dataset_ids(
            "token",
            "workspace-id",
            "Neemba SOS Analysis Report",
        )

        self.assertEqual(dataset_ids, ["364edd69-532c-4e10-867f-3b3d4dfdb6c7"])
        list_datasets.assert_not_called()

    def test_sos_and_fpr_resolve_their_own_rls_role_names(self):
        self.assertEqual(
            powerbi.resolve_dataset_roles("Neemba SOS Analysis Report", ["Global"]),
            ["Global User"],
        )
        self.assertEqual(
            powerbi.resolve_dataset_roles("FPR Global DB + RLS", ["Global"]),
            ["Global"],
        )
        self.assertEqual(
            powerbi.resolve_dataset_roles(
                "Neemba SOS Analysis Report",
                ["Boto/Mota", "Sangaredi/CBG"],
            ),
            ["Mota/Boto", "Sangaredi"],
        )

    def test_prime_movers_connection_includes_its_fpr_core_model(self):
        powerbi._local_powerbi_report_config.cache_clear()
        configured = next(
            item for item in powerbi._local_powerbi_report_config().get("reports", [])
            if item.get("report_id") == "7965812a-e2d7-4950-9651-a148d8fdd235"
        )

        self.assertEqual(configured["dataset_ids"], [
            "78f2e175-881d-42d7-8d64-fce27908e3c1",
            "364edd69-532c-4e10-867f-3b3d4dfdb6c7",
        ])

    @patch("reports.powerbi.get_dataset_metadata", return_value={})
    @patch("reports.powerbi.get_linked_powerbi_dataset_ids", return_value=["core-dataset"])
    @patch("reports.powerbi.get_report_hint_dataset_ids", return_value=[])
    @patch("reports.powerbi.get_report_connection_options")
    @patch("reports.powerbi.get_access_token", return_value="access-token")
    @patch("reports.powerbi.env_value")
    @patch("reports.powerbi.HTTP.post")
    def test_live_core_model_is_merged_with_saved_proxy_configuration(
        self,
        post,
        env_value,
        _access_token,
        connection_options,
        _hints,
        _linked,
        _metadata,
    ):
        env_value.side_effect = lambda key, default="": {
            "POWERBI_WORKSPACE_ID": "workspace-id",
            "POWERBI_EFFECTIVE_USERNAME": "",
        }.get(key, default)
        connection_options.return_value = {
            "dataset_ids": ["proxy-dataset"],
            "embed": {"effective_username": ""},
            "discover_live_dependencies": True,
        }
        response = Mock(status_code=200)
        response.json.return_value = {"token": "embed-token"}
        post.return_value = response
        report = PowerBIReport(
            id="report-id",
            name="Proxy report",
            display_name="Proxy report",
            dataset_id="proxy-dataset",
            web_url="https://app.powerbi.com/report",
            embed_url="https://app.powerbi.com/reportEmbed",
            report_type="PowerBIReport",
        )

        token = generate_report_embed_token(report, ["Global"])

        self.assertEqual(token, "embed-token")
        dataset_ids = [item["id"] for item in post.call_args.kwargs["json"]["datasets"]]
        self.assertEqual(dataset_ids, ["proxy-dataset", "core-dataset"])

    @patch("reports.powerbi.get_dataset_metadata", return_value={})
    @patch("reports.powerbi.get_linked_powerbi_dataset_ids")
    @patch("reports.powerbi.get_report_hint_dataset_ids", return_value=[])
    @patch("reports.powerbi.get_report_connection_options")
    @patch("reports.powerbi.get_access_token", return_value="access-token")
    @patch("reports.powerbi.env_value", return_value="workspace-id")
    @patch("reports.powerbi.HTTP.post")
    def test_validated_dependencies_and_embed_token_are_reused(
        self, post, _env, _access_token, connection_options, _hints, linked, metadata,
    ):
        connection_options.return_value = {
            "dataset_ids": ["configured-dataset"],
            "datasets": [{
                "id": "configured-dataset",
                "name": "Configured Model",
                "is_effective_identity_required": False,
                "is_effective_identity_roles_required": False,
            }],
            "embed": {"effective_username": ""},
        }
        response = Mock(status_code=200)
        response.json.return_value = {"token": "cached-embed-token"}
        post.return_value = response
        report = PowerBIReport(
            id="cached-report", name="Cached report", display_name="Cached report",
            dataset_id="configured-dataset", web_url="", embed_url="https://app.powerbi.com/reportEmbed",
            report_type="PowerBIReport",
        )

        first = generate_report_embed_token(report, ["Global"])
        second = generate_report_embed_token(report, ["Global"])

        self.assertEqual(first, "cached-embed-token")
        self.assertEqual(second, "cached-embed-token")
        self.assertEqual(post.call_count, 1)
        linked.assert_not_called()
        metadata.assert_not_called()

    @patch("reports.powerbi.get_latest_refresh", return_value=("2026-08-19 08:00 AM", "Completed"))
    @patch("reports.powerbi.get_access_token", return_value="token")
    @patch("reports.powerbi.env_value", return_value="workspace")
    @patch("reports.powerbi.list_workspace_reports")
    def test_refresh_history_is_cached_per_dataset(self, list_reports, _env, _token, latest_refresh):
        list_reports.return_value = [
            PowerBIReport("r1", "One", "One", "shared", "", "", "PowerBIReport"),
            PowerBIReport("r2", "Two", "Two", "shared", "", "", "PowerBIReport"),
            PowerBIReport("r3", "Three", "Three", "other", "", "", "PowerBIReport"),
        ]

        powerbi.list_workspace_reports_with_refresh()
        powerbi.list_workspace_reports_with_refresh()

        self.assertEqual(latest_refresh.call_count, 2)

    @patch("reports.powerbi.get_latest_refresh")
    @patch("reports.powerbi.get_access_token", return_value="token")
    @patch("reports.powerbi.env_value", return_value="workspace")
    @patch("reports.powerbi.list_workspace_reports")
    def test_one_refresh_failure_does_not_hide_other_reports(self, list_reports, _env, _token, latest_refresh):
        list_reports.return_value = [
            PowerBIReport("r1", "One", "One", "healthy", "", "", "PowerBIReport"),
            PowerBIReport("r2", "Two", "Two", "failed", "", "", "PowerBIReport"),
        ]

        def refresh_result(_token_value, _workspace, dataset_id, **_kwargs):
            if dataset_id == "failed":
                raise TimeoutError("Power BI timeout")
            return "2026-08-19 08:00 AM", "Completed"

        latest_refresh.side_effect = refresh_result
        reports = powerbi.list_workspace_reports_with_refresh()

        self.assertEqual(len(reports), 2)
        self.assertEqual(reports[0].refresh_status, "Completed")
        self.assertEqual(reports[1].refresh_status, "Unavailable")

    @patch("reports.powerbi.HTTP.post")
    def test_trigger_dataset_refresh_uses_semantic_model_endpoint(self, post):
        post.return_value = Mock(status_code=202)
        powerbi._REPORT_REFRESH_CACHE["workspace:dataset"] = (1.0, "Earlier", "Completed")

        powerbi.trigger_dataset_refresh("token", "workspace", "dataset")

        self.assertEqual(
            post.call_args.args[0],
            "https://api.powerbi.com/v1.0/myorg/groups/workspace/datasets/dataset/refreshes",
        )
        self.assertEqual(post.call_args.kwargs["json"], {"notifyOption": "NoNotification"})
        self.assertNotIn("workspace:dataset", powerbi._REPORT_REFRESH_CACHE)


class ReportingRefreshViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("report-user", password="secret")
        PlatformUser.objects.create(
            django_user=self.user,
            azure_ad_id="report-user-object",
            user_principal_name="report-user@example.com",
            display_name="Report User",
            can_access_reporting=True,
        )
        self.report_id = str(uuid4())
        self.report = PowerBIReport(
            self.report_id,
            "Fleet Report",
            "Fleet Report",
            "dataset-id",
            "https://app.powerbi.com/report",
            "https://app.powerbi.com/reportEmbed",
            "PowerBIReport",
            "2026-08-20 08:00 AM",
            "Completed",
        )
        self.client.force_login(self.user)

    @patch("reports.views.list_workspace_reports_with_refresh")
    def test_reporting_card_renders_refresh_action_and_status_hooks(self, list_reports):
        list_reports.return_value = [self.report]

        response = self.client.get(reverse("reporting"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-report-refresh")
        self.assertContains(response, 'data-dataset-id="dataset-id"')
        self.assertContains(response, reverse("reporting-report-refresh-api", args=[self.report_id]))
        self.assertContains(response, reverse("reporting-report-troubleshoot-api", args=[self.report_id]))
        self.assertContains(response, "Refresh report data")

    @patch("reports.views.get_latest_refresh", return_value=("2026-08-20 08:10 AM", "Failed"))
    @patch("reports.views.list_workspace_datasets", return_value=[{"id": "dataset-id", "name": "Fleet Model", "isRefreshable": True}])
    @patch("reports.views.trigger_dataset_refresh")
    @patch("reports.views.get_access_token", return_value="token")
    @patch("reports.views.env_value", return_value="workspace-id")
    @patch("reports.views.list_workspace_reports")
    def test_troubleshooting_restarts_a_failed_refresh(
        self, list_reports, _env, _token, trigger, _datasets, _latest
    ):
        list_reports.return_value = [self.report]

        response = self.client.post(
            reverse("reporting-report-troubleshoot-api", args=[self.report_id]),
            data="{}",
            content_type="application/json",
            HTTP_ACCEPT="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"]["status"], "Repair Started")
        self.assertTrue(response.json()["refresh"]["is_refreshing"])
        trigger.assert_called_once_with("token", "workspace-id", "dataset-id")

    @patch("reports.views.get_latest_refresh", return_value=("2026-08-20 08:10 AM", "Completed"))
    @patch("reports.views.list_workspace_datasets", return_value=[{"id": "dataset-id", "name": "Fleet Model", "isRefreshable": True}])
    @patch("reports.views.trigger_dataset_refresh")
    @patch("reports.views.get_access_token", return_value="token")
    @patch("reports.views.env_value", return_value="workspace-id")
    @patch("reports.views.list_workspace_reports")
    def test_troubleshooting_does_not_duplicate_a_healthy_refresh(
        self, list_reports, _env, _token, trigger, _datasets, _latest
    ):
        list_reports.return_value = [self.report]

        response = self.client.post(
            reverse("reporting-report-troubleshoot-api", args=[self.report_id]),
            data="{}",
            content_type="application/json",
            HTTP_ACCEPT="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"]["status"], "Healthy")
        trigger.assert_not_called()

    @patch("reports.views.trigger_dataset_refresh")
    @patch("reports.views.get_access_token", return_value="token")
    @patch("reports.views.env_value", return_value="workspace-id")
    @patch("reports.views.list_workspace_reports")
    def test_reporting_user_can_trigger_refresh(self, list_reports, _env, _token, trigger):
        list_reports.return_value = [self.report]

        response = self.client.post(
            reverse("reporting-report-refresh-api", args=[self.report_id]),
            data="{}",
            content_type="application/json",
            HTTP_ACCEPT="application/json",
        )

        self.assertEqual(response.status_code, 202)
        self.assertTrue(response.json()["is_refreshing"])
        trigger.assert_called_once_with("token", "workspace-id", "dataset-id")

    @patch("reports.views.get_latest_refresh", return_value=("2026-08-20 08:10 AM", "Unknown"))
    @patch("reports.views.get_access_token", return_value="token")
    @patch("reports.views.env_value", return_value="workspace-id")
    @patch("reports.views.list_workspace_reports")
    def test_refresh_status_normalizes_powerbi_unknown_as_refreshing(
        self, list_reports, _env, _token, _latest
    ):
        list_reports.return_value = [self.report]

        response = self.client.get(
            reverse("reporting-report-refresh-api", args=[self.report_id]),
            HTTP_ACCEPT="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "Refreshing")
        self.assertTrue(response.json()["is_refreshing"])

    def test_user_without_reporting_access_cannot_refresh(self):
        blocked = User.objects.create_user("blocked", password="secret")
        PlatformUser.objects.create(
            django_user=blocked,
            azure_ad_id="blocked-object",
            user_principal_name="blocked@example.com",
            display_name="Blocked User",
        )
        self.client.force_login(blocked)

        response = self.client.post(
            reverse("reporting-report-refresh-api", args=[self.report_id]),
            data="{}",
            content_type="application/json",
            HTTP_ACCEPT="application/json",
        )

        self.assertEqual(response.status_code, 403)
