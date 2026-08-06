import io
from contextlib import contextmanager
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from .data_browsers import DataBrowserValidationError, insert_browser_record
from .external_data_browsers import preview_external_browser_data
from .models import DataBrowser, DataBrowserColumn


class FakeCursor:
    def __init__(self):
        self.query_count = 0

    def execute(self, query, params=()):
        self.query_count += 1
        return self

    def fetchone(self):
        return [2]

    def fetchall(self):
        return [
            [101, "EQ-101", "Active"],
            [102, "EQ-102", "Inactive"],
        ]


class FakeConnection:
    def __init__(self):
        self._cursor = FakeCursor()

    def cursor(self):
        return self._cursor


class MiningProdBrowserBootstrapTests(TestCase):
    def test_preview_does_not_write(self):
        output = io.StringIO()
        call_command("sync_miningprod_browsers", preview=True, stdout=output)
        self.assertEqual(DataBrowser.objects.count(), 0)
        self.assertIn("Browsers selected: 21", output.getvalue())
        self.assertIn("OpenAI API calls: 0", output.getvalue())

    def test_apply_is_idempotent_and_read_only(self):
        call_command("sync_miningprod_browsers", apply=True, stdout=io.StringIO())
        call_command("sync_miningprod_browsers", apply=True, stdout=io.StringIO())

        browsers = DataBrowser.objects.filter(source_mode="miningprod_metaform")
        self.assertEqual(browsers.count(), 21)
        self.assertEqual(
            DataBrowserColumn.objects.filter(browser__in=browsers).count(),
            318,
        )
        self.assertFalse(browsers.filter(allow_create=True).exists())
        self.assertFalse(browsers.filter(allow_edit=True).exists())
        self.assertFalse(browsers.filter(allow_delete=True).exists())
        self.assertEqual(browsers.filter(allow_export=True).count(), 21)

    def test_external_preview_uses_normalized_browser_shape(self):
        call_command(
            "sync_miningprod_browsers",
            apply=True,
            form_ids=[45],
            stdout=io.StringIO(),
        )
        browser = DataBrowser.objects.prefetch_related("columns").get(external_form_id=45)

        @contextmanager
        def fake_connection(_browser):
            yield FakeConnection()

        with patch(
            "reports.external_data_browsers.external_browser_connection",
            fake_connection,
        ):
            result = preview_external_browser_data(browser, limit=2)

        self.assertEqual(result["columns"][0], "BrowserRecordId")
        self.assertEqual(result["row_count"], 2)
        self.assertEqual(result["total_count"], 2)
        self.assertEqual(result["rows"][0]["BrowserRecordId"], 101)

    def test_external_writes_remain_blocked_until_mapping_validation(self):
        call_command(
            "sync_miningprod_browsers",
            apply=True,
            form_ids=[45],
            stdout=io.StringIO(),
        )
        browser = DataBrowser.objects.prefetch_related("columns").get(external_form_id=45)
        with self.assertRaisesMessage(
            DataBrowserValidationError,
            "disabled until the MiningProd write mapping has been validated",
        ):
            insert_browser_record(browser, {"Equipment": "TEST"})
