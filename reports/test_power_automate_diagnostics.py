from unittest.mock import Mock, patch

import requests
from django.test import SimpleTestCase

from reports.power_automate import PowerAutomateTransientError, execute_dax_via_flow


class PowerAutomateDiagnosticsTests(SimpleTestCase):
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
