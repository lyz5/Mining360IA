import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from . import powerbi


class PowerBITokenRuntimeTests(SimpleTestCase):
    def tearDown(self):
        powerbi._ACCESS_TOKEN_CACHE = None

    def test_concurrent_cold_requests_share_one_entra_token_acquisition(self):
        powerbi._ACCESS_TOKEN_CACHE = None
        call_count = 0
        count_lock = threading.Lock()

        def token_response(*_args, **_kwargs):
            nonlocal call_count
            with count_lock:
                call_count += 1
            time.sleep(0.05)
            response = Mock(status_code=200, text="")
            response.json.return_value = {
                "access_token": "server-only-token",
                "expires_in": 3600,
            }
            return response

        with (
            patch("reports.powerbi.env_value", side_effect=lambda name, default=None: {
                "POWERBI_TENANT_ID": "tenant",
                "POWERBI_CLIENT_ID": "client",
                "POWERBI_CLIENT_SECRET": "secret",
                "POWERBI_SCOPE": powerbi.POWERBI_SCOPE,
            }.get(name, default)),
            patch.object(powerbi.HTTP, "post", side_effect=token_response),
            ThreadPoolExecutor(max_workers=4) as executor,
        ):
            tokens = list(executor.map(lambda _index: powerbi.get_access_token(), range(4)))

        self.assertEqual(tokens, ["server-only-token"] * 4)
        self.assertEqual(call_count, 1)

    def test_cached_token_uses_provider_expiration_with_safety_margin(self):
        response = Mock(status_code=200, text="")
        response.json.return_value = {"access_token": "cached-token", "expires_in": 3600}
        powerbi._ACCESS_TOKEN_CACHE = None

        with (
            patch("reports.powerbi.env_value", return_value="configured"),
            patch.object(powerbi.HTTP, "post", return_value=response) as post,
        ):
            first = powerbi.get_access_token()
            second = powerbi.get_access_token()

        self.assertEqual(first, second)
        self.assertEqual(post.call_count, 1)
        self.assertGreater(powerbi._ACCESS_TOKEN_CACHE[0], time.monotonic() + 3000)
