from unittest.mock import Mock, patch

from django.conf import settings
from django.test import SimpleTestCase

from .powerbi import PowerBIReport, generate_report_embed_token


class PowerBIReportEmbeddingTests(SimpleTestCase):
    def test_powerbi_client_is_served_locally_in_every_embed_surface(self):
        template_root = settings.BASE_DIR / "reports" / "templates" / "reports"
        for template_name in ("detail.html", "ai.html", "knowledge_base.html"):
            source = (template_root / template_name).read_text(encoding="utf-8")
            with self.subTest(template=template_name):
                self.assertIn("reports/vendor/powerbi-client-2.23.7.min.js", source)
                self.assertNotIn("cdn.jsdelivr.net/npm/powerbi-client", source)

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
