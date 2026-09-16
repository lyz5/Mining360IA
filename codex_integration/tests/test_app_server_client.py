from io import StringIO
import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, patch

from codex_integration.app_server_client import (
    build_initialize_request,
    probe_app_server_handshake,
)


class AppServerClientTests(TestCase):
    def test_initialize_request_disables_experimental_api(self):
        request = build_initialize_request(17)

        self.assertEqual(request["id"], 17)
        self.assertEqual(request["method"], "initialize")
        self.assertFalse(request["params"]["capabilities"]["experimentalApi"])

    @patch("codex_integration.app_server_client.Path.mkdir")
    @patch("codex_integration.app_server_client.subprocess.Popen")
    def test_probe_initializes_without_starting_thread_or_turn(self, popen, mkdir):
        response = {
            "id": 1,
            "result": {
                "codexHome": "C:/isolated/codex",
                "platformFamily": "windows",
                "platformOs": "windows",
                "userAgent": "codex_cli_rs/0.154.0",
            },
        }
        process = MagicMock()
        process.stdin = StringIO()
        process.stdout = StringIO(json.dumps(response) + "\n")
        process.poll.return_value = None
        popen.return_value = process

        result = probe_app_server_handshake(
            cli_path="codex",
            codex_home=Path("isolated-codex-home"),
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.platform_os, "windows")
        written = process.stdin.getvalue()
        self.assertIn('"method":"initialize"', written)
        self.assertIn('"method":"initialized"', written)
        self.assertNotIn("thread/start", written)
        self.assertNotIn("turn/start", written)
        process.terminate.assert_called_once()

    @patch("codex_integration.app_server_client.Path.mkdir")
    @patch("codex_integration.app_server_client.subprocess.Popen")
    def test_probe_reports_protocol_error(self, popen, mkdir):
        process = MagicMock()
        process.stdin = StringIO()
        process.stdout = StringIO(
            json.dumps({"id": 1, "error": {"message": "Not available"}}) + "\n"
        )
        process.poll.return_value = 0
        popen.return_value = process

        result = probe_app_server_handshake(
            cli_path="codex",
            codex_home=Path("isolated-codex-home"),
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "Not available")
