from unittest.mock import Mock, patch

import requests
from django.test import SimpleTestCase

from reports.power_automate import PowerAutomateTransientError, execute_dax_via_flow, get_flow_url


class PowerAutomateDiagnosticsTests(SimpleTestCase):
    @patch.dict(
        "os.environ",
        {
            "POWER_AUTOMATE_DAX_FLOW_URL": "https://flow.example/fpr",
            "POWER_AUTOMATE_AFTERMARKET_DAX_FLOW_URL": "https://flow.example/aftermarket",
            "POWER_AUTOMATE_LOGISTICS_DAX_FLOW_URL": "https://flow.example/logistics",
        },
    )
    def test_aftermarket_dataset_uses_inspect_data_2(self):
        self.assertEqual(
            get_flow_url("Mine Logistics & AfterMarket"),
            "https://flow.example/aftermarket",
        )
        self.assertEqual(
            get_flow_url("FPR Global DB + RLS"),
            "https://flow.example/fpr",
        )
        self.assertEqual(
            get_flow_url("Mine Logistics Report"),
            "https://flow.example/logistics",
        )

    @patch.dict("os.environ", {"POWER_AUTOMATE_AFTERMARKET_DAX_FLOW_URL": ""}, clear=False)
    @patch("reports.system_configuration_service.integration_value", return_value="")
    @patch("reports.power_automate._local_powerbi_credentials", return_value={})
    def test_aftermarket_flow_does_not_fall_back_to_fpr(self, _credentials, _integration):
        with self.assertRaisesRegex(RuntimeError, "inspectData2 is not configured"):
            execute_dax_via_flow({"datasetName": "Mine Logistics & AfterMarket", "query": "EVALUATE ROW()"})

    @patch.dict("os.environ", {"POWER_AUTOMATE_LOGISTICS_DAX_FLOW_URL": ""}, clear=False)
    @patch("reports.system_configuration_service.integration_value", return_value="")
    @patch("reports.power_automate._local_powerbi_credentials", return_value={})
    def test_logistics_flow_does_not_fall_back_to_other_flows(self, _credentials, _integration):
        with self.assertRaisesRegex(RuntimeError, "inspectData3 is not configured"):
            execute_dax_via_flow({"datasetName": "Mine Logistics Report", "query": "EVALUATE ROW()"})

    @patch("reports.power_automate.time.sleep")
    @patch("reports.power_automate.get_flow_url", return_value="https://secret-flow.example/?sig=secret")
    @patch("reports.power_automate.HTTP.post")
    def test_transient_status_reports_safe_reference(self, post, _flow_url, _sleep):
        response = Mock(status_code=503, text="unavailable", headers={"x-ms-request-id": "request-123"})
        post.return_value = response
        with self.assertRaisesRegex(PowerAutomateTransientError, "HTTP 503.*request-123"):
            execute_dax_via_flow({"query": "EVALUATE ROW(\"Value\", 1)"})

    @patch("reports.power_automate.time.sleep")
    @patch("reports.power_automate.get_flow_url", return_value="https://secret-flow.example/?sig=secret")
    @patch("reports.power_automate.HTTP.post")
    def test_connection_error_does_not_expose_signed_url(self, post, _flow_url, _sleep):
        post.side_effect = requests.ConnectionError("https://secret-flow.example/?sig=secret")
        with self.assertRaises(PowerAutomateTransientError) as captured:
            execute_dax_via_flow({"query": "EVALUATE ROW(\"Value\", 1)"})
        self.assertNotIn("secret-flow", str(captured.exception))
        self.assertNotIn("sig=", str(captured.exception))
