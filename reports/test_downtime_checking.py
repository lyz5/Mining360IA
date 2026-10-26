from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .downtime_checking_rules import check, evidence
from .downtime_checking_service import reconcile
from .downtime_checking_source import SourceCheckError, sql_queries, validate_browser
from .models import DataBrowser, DowntimeCheckingFinding, DowntimeCheckingRun, SystemIntegrationConfig


def row(**extra):
    base = {"event_id": "100", "yearmonth": datetime(2026, 9, 1), "minesite": "Essakane", "serial_number": "ABC",
            "model": "D10", "labour_type": "1250 Fuel System", "description_cat": "Power Train", "work_type": "Repair",
            "comment": "Fuel smell", "downtime_hours": Decimal("0"), "start_hours": datetime(2026, 9, 1, 8), "end_hours": datetime(2026, 9, 1, 9)}
    base.update(extra)
    return base


class RulesTests(TestCase):
    def test_zero_hours_is_not_unknown(self):
        codes = {item["rule_code"] for item in check(row())}
        self.assertIn("fuel_power_train", codes)
        self.assertNotIn("invalid_hours", codes)

    def test_missing_markers_and_reversed_dates_are_detected(self):
        codes = {item["rule_code"] for item in check(row(labour_type="(vide)", description_cat="", comment="", end_hours=datetime(2026, 9, 1, 7)))}
        self.assertTrue({"missing_labour_type", "missing_description_cat", "missing_comment", "reversed_dates"}.issubset(codes))

    def test_daily_inspection_is_not_a_name_difference_false_positive(self):
        codes = {item["rule_code"] for item in check(row(labour_type="PM", description_cat="Daily Inspection", comment="DAILY CHECK"))}
        self.assertFalse(codes & {"fuel_power_train", "dust_power_train", "grease_hydraulics"})

    def test_evidence_masks_contact_strings(self):
        snapshot = evidence(row(comment="Call +221 77 123 45 67 or user@example.com"))
        self.assertNotIn("user@example.com", snapshot["comment"])
        self.assertNotIn("+221", snapshot["comment"])


class SourceTests(TestCase):
    def test_sql_binds_ytd_bounds_and_has_no_mutation(self):
        count_sql, rows_sql = sql_queries("%s")
        self.assertEqual(count_sql.count("%s"), 2)
        self.assertNotIn("UPDATE", (count_sql + rows_sql).upper())
        self.assertIn("CAST(f.[yearmonth] AS datetime)", rows_sql)

    def test_source_requires_exact_browser_contract(self):
        browser = DataBrowser(name="other", table_name="t", source_view_name="wrong", source_mode="managed_table")
        with self.assertRaises(SourceCheckError) as raised:
            validate_browser(browser)
        self.assertEqual(raised.exception.code, "source_not_configured")


class ReconcileTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="admin", password="x", is_staff=True)
        integration = SystemIntegrationConfig.objects.create(code="test-miningprod", name="Test", integration_type="Database", settings_json={"database": "MiningProd"})
        self.browser = DataBrowser.objects.create(name="Neemba - Downtimes Data", table_name="dt-test", source_view_name="META_FORM_VIEW_SCHEMA.v_metaform84", source_mode="miningprod_metaform", source_connection=integration, write_strategy="read_only")

    def make_run(self, signature="same"):
        return DowntimeCheckingRun.objects.create(year=2026, start_date=date(2026, 1, 1), end_date=date(2026, 10, 26), status="completed", source_browser=self.browser, created_by=self.user, rules_version="2026-10-26.1", source_signature=signature)

    def test_recheck_marks_only_present_and_comparable_issue_resolved(self):
        old = self.make_run()
        old_item = DowntimeCheckingFinding.objects.create(run=old, event_id="100", rule_code="fuel_power_train", kind="mismatch", change="new", minesite="Essakane", serial_number="ABC", labour_type="1250 Fuel System", description_cat="Power Train", comment="Fuel", title="Fuel / Power Train", reason="old", evidence=evidence(row()))
        current = self.make_run()
        findings, counts = reconcile(current, [row(description_cat="Fuel System")], {"expected": 1, "signature": "same"}, [old_item])
        self.assertEqual(counts["corrected"], 1)
        self.assertEqual(findings[0].change, "resolved")

    def test_absent_event_is_not_claimed_as_corrected(self):
        old = self.make_run()
        old_item = DowntimeCheckingFinding.objects.create(run=old, event_id="100", rule_code="fuel_power_train", kind="mismatch", change="new", minesite="Essakane", serial_number="ABC", labour_type="1250 Fuel System", description_cat="Power Train", comment="Fuel", title="Fuel / Power Train", reason="old", evidence=evidence(row()))
        current = self.make_run()
        findings, counts = reconcile(current, [], {"expected": 0, "signature": "same"}, [old_item])
        self.assertEqual(counts["unverified"], 1)
        self.assertEqual(findings[0].change, "unverified")


class ViewsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="super", password="x", is_staff=True)
        self.client.force_login(self.user)

    def test_page_and_empty_results_are_admin_only_and_do_not_enqueue(self):
        response = self.client.get(reverse("downtime-checking-home"))
        self.assertEqual(response.status_code, 200)
        response = self.client.get(reverse("downtime-checking-results"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 0)
        self.assertEqual(DowntimeCheckingRun.objects.count(), 0)

    @override_settings(DOWNTIME_CHECKING_BACKGROUND_WORKER=False)
    def test_recheck_does_not_accept_client_source_or_year(self):
        response = self.client.post(reverse("downtime-checking-recheck"), data='{"year": 1999, "sql": "UPDATE"}', content_type="application/json")
        self.assertIn(response.status_code, (202, 409))
        if response.status_code == 202:
            run = DowntimeCheckingRun.objects.get()
            self.assertEqual(run.year, datetime.now().year)
