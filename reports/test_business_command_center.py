from datetime import date
from pathlib import Path

from django.contrib.auth.models import Permission, User
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .business_command_center_service import BusinessRevenuePeriodService, _growth
from .machine_sales_service import MachineSalesDetailService
from .business_mapping_country_scope import operating_country_label
from .models import (
    MachineSaleDetail,
    MachineSalesSynchronizationRun,
    MappingPublication,
    MappingSynchronizationRun,
    RevenueSourceSnapshot,
)


FEATURES = {
    "ENABLE_BUSINESS_REVIEW": "Production",
    "ENABLE_BUSINESS_COMMAND_CENTER": "Production",
    "ENABLE_BUSINESS_COMMAND_CENTER_V2": "Production",
    "ENABLE_BUSINESS_COMMAND_CENTER_CUSTOMERS": "Production",
    "ENABLE_BUSINESS_COMMAND_CENTER_COUNTRIES": "Production",
    "ENABLE_BUSINESS_COMMAND_CENTER_KEY_ACCOUNTS": "Production",
    "ENABLE_BUSINESS_COMMAND_CENTER_LAST_VISIT": "Production",
    "ENABLE_BUSINESS_COMMAND_CENTER_WATCHLIST": "Production",
}


@override_settings(**FEATURES)
class BusinessRevenuePeriodTests(TestCase):
    def test_exact_period_contracts(self):
        latest = date(2026, 9, 8)
        ytd = BusinessRevenuePeriodService.resolve(latest, "ytd")
        self.assertEqual((ytd["start_date"], ytd["end_date"]), (date(2026, 1, 1), latest))
        self.assertEqual((ytd["comparison_start_date"], ytd["comparison_end_date"]), (date(2025, 1, 1), date(2025, 9, 8)))
        last_year = BusinessRevenuePeriodService.resolve(latest, "last_year")
        self.assertEqual((last_year["start_date"], last_year["end_date"]), (date(2025, 1, 1), date(2025, 12, 31)))
        current_month = BusinessRevenuePeriodService.resolve(latest, "current_month")
        self.assertEqual((current_month["start_date"], current_month["end_date"]), (date(2026, 9, 1), latest))
        self.assertEqual(current_month["label"], "MTD Sep 2026")
        year_2024 = BusinessRevenuePeriodService.resolve(latest, "2024")
        self.assertEqual((year_2024["start_date"], year_2024["end_date"]), (date(2024, 1, 1), date(2024, 12, 31)))
        self.assertEqual((year_2024["comparison_start_date"], year_2024["comparison_end_date"]), (date(2023, 1, 1), date(2023, 12, 31)))
        year_2023 = BusinessRevenuePeriodService.resolve(latest, "2023")
        self.assertEqual((year_2023["start_date"], year_2023["end_date"]), (date(2023, 1, 1), date(2023, 12, 31)))
        self.assertEqual(year_2023["comparison"], "none")
        self.assertIsNone(year_2023["comparison_start_date"])
        custom = BusinessRevenuePeriodService.resolve(latest, "custom", "2026-02-01", "2026-02-28", "previous_equivalent_period")
        self.assertEqual((custom["comparison_start_date"], custom["comparison_end_date"]), (date(2026, 1, 4), date(2026, 1, 31)))

    def test_growth_states_do_not_emit_misleading_percentages(self):
        self.assertEqual(_growth(100, 0), (None, "new"))
        self.assertEqual(_growth(0, 0), (None, "no_change"))
        self.assertEqual(_growth(100, 1), (None, "not_meaningful"))
        self.assertEqual(_growth(1500, -1000), (None, "not_meaningful"))

    def test_country_codes_use_governed_executive_names(self):
        self.assertEqual(operating_country_label("BF"), "Burkina Faso")
        self.assertEqual(operating_country_label("GN"), "Guinea")
        self.assertEqual(operating_country_label("CI"), "Cote d'Ivoire")
        self.assertEqual(operating_country_label("Mali"), "Mali")


@override_settings(**FEATURES)
class BusinessCommandCenterApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("command-admin", "command@example.com", "password")
        self.client = Client()
        self.client.force_login(self.user)
        self.run = MappingSynchronizationRun.objects.create(
            source="Customer Fleet & Revenue Planning Model", status="Completed", progress_percent=100,
            completed_at=timezone.now(), source_context_json={"semantic_data_through": "2026-09-08"},
        )
        values = {
            "PRIME": 1000,
            "PARTS": 2000,
            "SERVICE": 300,
            "RENTAL": 200,
        }
        for index, (lob, amount) in enumerate(values.items()):
            self._revenue(f"current-{index}", "C001", lob, date(2026, 9, 8), amount)
            self._revenue(f"previous-{index}", "C001", lob, date(2025, 9, 8), amount / 2)

    def _revenue(self, record_id, account, lob, business_date, amount, division="MI"):
        return RevenueSourceSnapshot.objects.create(
            synchronization_run=self.run, source_record_id=record_id, source_account_code=account,
            source_account_name="Fekola Customer", business_date=business_date, source_lob=lob, lob=lob,
            division=division, period_year=business_date.year, revenue_eur=amount, revenue_ytd_eur=amount,
            source_hash=record_id, source_last_seen_at=timezone.now(),
        )

    def test_page_and_bootstrap_load_without_published_mapping(self):
        page = self.client.get(reverse("business-command-center"))
        self.assertEqual(page.status_code, 200)
        self.assertTemplateUsed(page, "reports/business_command_center_v2.html")
        self.assertContains(page, "Business Overview")
        self.assertNotContains(page, "Business Command Center")
        self.assertContains(page, 'data-workspace="turnover"')
        self.assertNotContains(page, 'data-workspace-tab="explore"')
        self.assertContains(page, "Projects &amp; Tenders", count=2)
        self.assertContains(page, "Updating Business Overview")
        self.assertContains(page, "data-update-loader")
        self.assertContains(page, '<option value="custom">Custom Range</option>', html=True)
        self.assertContains(page, "Start Date")
        self.assertContains(page, "End Date")
        self.assertContains(page, "All Divisions")
        self.assertContains(page, 'data-division-toggle')
        self.assertContains(page, 'value="mining" data-filter="division_scope"')
        self.assertNotContains(page, "Revenue Mix &amp; Movement")
        response = self.client.get(reverse("business-command-center-bootstrap-api"))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["mode"], "unmapped_business_line")
        self.assertEqual(data["hero"]["revenue"], 3500.0)
        self.assertEqual(sum(item["revenue"] for item in data["business_lines"]), 3500.0)
        self.assertEqual(data["reconciliation"]["status"], "RECONCILED")
        self.assertEqual(data["context"]["end_date"], "2026-09-08")
        self.assertNotIn("sales_review", data)
        self.assertTrue(data["context"]["context_id"])
        self.assertLessEqual(len(data["dimensions"]["customers"]), 5)
        self.assertEqual(data["daily_trend"][0]["date"], "2026-09-08")
        self.assertEqual(data["daily_trend"][0]["value"], 3500.0)
        self.assertEqual(data["since_yesterday"]["from_date"], "2026-09-07")
        self.assertEqual(data["since_yesterday"]["through_date"], "2026-09-08")
        self.assertEqual(sum(item["absolute_delta"] for item in data["since_yesterday"]["items"]), 3500.0)

    def test_all_divisions_is_explicit_and_preserves_mining_default(self):
        self._revenue("tp-current", "C002", "PRIME", date(2026, 9, 8), 600, division="TP")
        self._revenue("tp-previous", "C002", "PRIME", date(2025, 9, 8), 300, division="TP")
        self._revenue("mo-current", "C003", "SERVICE", date(2026, 9, 8), 400, division="MO")
        self._revenue("mo-previous", "C003", "SERVICE", date(2025, 9, 8), 200, division="MO")
        self._revenue("zz-current", "C004", "PARTS", date(2026, 9, 8), 5000, division="ZZ")

        mining = self.client.get(reverse("business-command-center-bootstrap-api")).json()
        all_divisions = self.client.get(
            reverse("business-command-center-bootstrap-api"),
            {"division_scope": "all_divisions"},
        ).json()

        self.assertEqual(mining["context"]["division_scope"], "mining")
        self.assertEqual(mining["context"]["division_codes"], ["MI"])
        self.assertEqual(mining["hero"]["revenue"], 3500.0)
        self.assertEqual(all_divisions["context"]["division_scope"], "all_divisions")
        self.assertEqual(all_divisions["context"]["division_codes"], ["MI", "TP", "MO"])
        self.assertEqual(all_divisions["hero"]["revenue"], 4500.0)
        self.assertEqual(all_divisions["hero"]["comparison_revenue"], 2250.0)
        self.assertNotEqual(mining["context"]["context_id"], all_divisions["context"]["context_id"])

    def test_unknown_division_scope_is_rejected(self):
        response = self.client.get(
            reverse("business-command-center-bootstrap-api"),
            {"division_scope": "uncontrolled"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["status"], "INVALID_CONTEXT")

    def test_business_overview_is_the_default_home_and_first_menu_item(self):
        response = self.client.get(reverse("dashboard"))
        self.assertRedirects(response, reverse("business-command-center"), fetch_redirect_response=False)

        page = self.client.get(reverse("business-command-center"))
        content = page.content.decode("utf-8")
        self.assertLess(content.index("Business Overview</span>"), content.index("Excellence Center</span>"))

    def test_excellence_center_remains_available_on_its_own_route(self):
        response = self.client.get(reverse("excellence-center"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "reports/dashboard.html")

    def test_business_overview_tracks_the_actual_sidebar_width(self):
        css = Path(__file__).parent.joinpath(
            "static/reports/business_command_center_v2.css"
        ).read_text(encoding="utf-8")

        self.assertIn(
            ".bcc-body:not(.presentation) .bcc-shell{margin-left:var(--sidebar-width);transition:none}",
            css,
        )
        self.assertIn(
            "@media(max-width:720px){.bcc-body:not(.presentation) .bcc-shell{margin-left:0}}",
            css,
        )

    def test_home_falls_back_to_excellence_center_without_revenue_access(self):
        restricted_user = User.objects.create_user("restricted-home", password="password")
        self.client.force_login(restricted_user)

        response = self.client.get(reverse("dashboard"))

        self.assertRedirects(response, reverse("excellence-center"), fetch_redirect_response=False)

    def test_admin_can_open_legacy_rollback_view(self):
        page = self.client.get(reverse("business-command-center"), {"ui": "legacy"})
        self.assertTemplateUsed(page, "reports/business_command_center_legacy.html")
        payload = self.client.get(reverse("business-command-center-bootstrap-api"), {"ui": "legacy"}).json()
        self.assertIn("sales_review", payload)

    def test_business_line_and_period_filters_intersect(self):
        data = self.client.get(reverse("business-command-center-bootstrap-api"), {
            "period": "ytd", "business_line": "parts", "comparison": "same_period_last_year",
        }).json()
        self.assertEqual(data["hero"]["revenue"], 2000.0)
        self.assertEqual(data["hero"]["comparison_revenue"], 1000.0)
        self.assertEqual(data["hero"]["relative_delta"], 100.0)

    def test_published_mapping_enables_canonical_dimensions_without_double_counting(self):
        MappingPublication.objects.create(
            version=1, status="Published", mapping_count=1, account_count=1, minesite_count=1,
            published_by=self.user, published_at=timezone.now(), snapshot_json={"mappings": [{
                "mapping_id": "M1", "account_id": "A1", "account_code": "ACC-1",
                "account_name": "Fekola Canonical", "minesite_id": "S1", "minesite_name": "Fekola",
                "source_account_codes": ["C001"], "business_country": "ML",
                "customer_country_group_id": "CCG1", "customer_country_group_name": "B2Gold Mali",
                "key_account_id": "K1", "key_account_name": "B2Gold",
            }]},
        )
        data = self.client.get(reverse("business-command-center-bootstrap-api"), {"business_line": "parts"}).json()
        self.assertTrue(data["mapping_ready"])
        self.assertEqual(data["dimensions"]["customers"][0]["revenue"], 2000.0)
        self.assertEqual(data["dimensions"]["countries"][0]["revenue"], 2000.0)
        self.assertEqual(data["dimensions"]["countries"][0]["id"], "ML")
        self.assertEqual(data["dimensions"]["countries"][0]["name"], "Mali")
        self.assertEqual(data["filter_options"]["countries"], [{"id": "ML", "name": "Mali"}])
        self.assertEqual(data["dimensions"]["key_accounts"][0]["revenue"], 2000.0)
        explorer = self.client.get(reverse("business-command-center-revenue-explorer-api"), {
            "business_line": "parts", "dimension": "customers",
        }).json()
        self.assertEqual(explorer["results"][0]["name"], "Fekola Canonical")
        self.assertEqual(explorer["results"][0]["revenue"], 2000.0)
        self.assertEqual(explorer["results"][0]["comparison_business_line_mix"]["parts"], 1000.0)
        country_explorer = self.client.get(reverse("business-command-center-revenue-explorer-api"), {
            "business_line": "parts", "dimension": "countries",
        }).json()
        self.assertEqual(country_explorer["results"][0]["name"], "Mali")
        customer_groups = self.client.get(reverse("business-command-center-customer-search-api"), {"q": "b2gold"}).json()
        self.assertEqual(customer_groups["results"], [{"id": "CCG1", "name": "B2Gold Mali", "country": "Mali", "revenue": 3500.0}])
        filtered = self.client.get(reverse("business-command-center-bootstrap-api"), {
            "business_line": "parts", "customer_group_ids": "CCG1",
        }).json()
        self.assertEqual(filtered["hero"]["revenue"], 2000.0)
        self.assertEqual(filtered["filter_options"]["customers"][0]["name"], "B2Gold Mali")

    def test_published_key_account_classification_does_not_require_a_minesite_mapping(self):
        MappingPublication.objects.create(
            version=1, status="Published", mapping_count=0, account_count=1, minesite_count=0,
            published_by=self.user, published_at=timezone.now(), snapshot_json={
                "mappings": [],
                "accounts": [{
                    "account_id": "A-CORICA", "account_code": "ACC-CORICA",
                    "account_name": "CORICA GUINEA", "source_account_codes": ["C001"],
                    "business_country": "Guinea", "key_account_id": "K-CORICA",
                    "key_account_name": "CORICA", "minesite_names": [],
                }],
            },
        )
        data = self.client.get(reverse("business-command-center-bootstrap-api"), {"business_line": "parts"}).json()
        self.assertEqual(data["dimensions"]["key_accounts"][0]["name"], "CORICA")
        self.assertEqual(data["dimensions"]["key_accounts"][0]["revenue"], 2000.0)
        self.assertEqual(data["filter_options"]["key_accounts"], [])
        search = self.client.get(reverse("business-command-center-key-account-search-api"), {"q": "cori"}).json()
        self.assertEqual(search["results"][0]["name"], "CORICA")
        dropdown = self.client.get(reverse("business-command-center-key-account-search-api")).json()
        self.assertEqual(dropdown["results"][0]["name"], "CORICA")

    def test_watchlist_is_persisted_per_user(self):
        url = reverse("business-command-center-watchlist-api")
        response = self.client.post(url, data='{"entity_type":"country","entity_id":"ML","display_name":"Mali"}', content_type="application/json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.client.get(url).json()["results"][0]["display_name"], "Mali")

    def test_machine_sales_detail_is_period_filtered_and_paginated(self):
        RevenueSourceSnapshot.objects.filter(
            active=True,
            source_account_code="C001",
            lob="PRIME",
            business_date=date(2026, 9, 8),
        ).update(revenue_eur=3940840.10, revenue_ytd_eur=3940840.10)
        machine_run = MachineSalesSynchronizationRun.objects.create(
            status="Completed", data_through_date=date(2026, 9, 8), completed_at=timezone.now(), records_read=2,
        )
        MachineSaleDetail.objects.create(
            source_record_id="machine-current", business_date=date(2026, 9, 8), customer_code="C001",
            customer_name="Fekola Customer", equipment_key="E1", equipment_code="266885",
            serial_number="6P300144", model_code="6030", model_name="6030", equipment_family="Hydraulic Mining Shovels",
            family_code="HMS", brand="CAT", product_category="Machine Lourde", invoice_number="80000650",
            distribution_channel="On", sale_status_code="FA", new_used_code="N", net_revenue_eur=3940740.10,
            source_hash="machine-current", synchronization_run=machine_run, source_last_seen_at=timezone.now(),
        )
        MachineSaleDetail.objects.create(
            source_record_id="machine-current-misc", business_date=date(2026, 9, 8), customer_code="C001",
            customer_name="Fekola Customer", equipment_key="E1", equipment_code="266885",
            serial_number="6P300144", model_code="6030", model_name="6030", equipment_family="Hydraulic Mining Shovels",
            family_code="HMS", brand="CAT", product_category="MISC", invoice_number="80000650",
            distribution_channel="On", new_used_code="N", net_revenue_eur=100,
            source_hash="machine-current-misc", synchronization_run=machine_run, source_last_seen_at=timezone.now(),
        )
        MachineSaleDetail.objects.create(
            source_record_id="machine-old", business_date=date(2025, 9, 8), customer_code="C001",
            customer_name="Fekola Customer", equipment_key="E2", serial_number="OLD", model_code="785B",
            invoice_number="OLD-INVOICE", distribution_channel="On", net_revenue_eur=100,
            source_hash="machine-old", synchronization_run=machine_run, source_last_seen_at=timezone.now(),
        )
        response = self.client.get(reverse("business-command-center-machine-sales-api"), {"period": "ytd", "page_size": 1})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ready"])
        self.assertEqual(data["summary"]["equipment_count"], 1)
        self.assertEqual(data["summary"]["invoice_count"], 1)
        self.assertEqual(data["results"][0]["serial_number"], "6P300144")
        self.assertEqual(data["results"][0]["model_name"], "6030")
        self.assertEqual(data["results"][0]["family_code"], "HMS")
        self.assertEqual(data["results"][0]["brand"], "CAT")
        self.assertEqual(data["results"][0]["machine_sale_eur"], 3940740.1)
        self.assertEqual(data["results"][0]["other_charges_eur"], 100.0)
        self.assertEqual(data["results"][0]["net_revenue_eur"], 3940840.1)
        self.assertEqual(data["results"][0]["transaction_count"], 2)
        self.assertEqual(
            {entry["classification"] for entry in data["results"][0]["entries"]},
            {"Machine Sale", "Other Charges & Adjustments"},
        )
        self.assertEqual(data["filter_options"]["families"], ["HMS"])
        self.assertEqual(data["filter_options"]["family_groups"][0]["code"], "HMS")
        self.assertEqual(data["filter_options"]["family_groups"][0]["equipment_count"], 1)
        self.assertEqual(data["summary"]["net_revenue_eur"], 3940840.1)
        self.assertEqual(data["summary"]["reconciliation_adjustment_eur"], 0.0)

    def test_machine_sales_reconciles_detail_grain_to_certified_card(self):
        machine_run = MachineSalesSynchronizationRun.objects.create(
            status="Completed", data_through_date=date(2026, 9, 8), completed_at=timezone.now(), records_read=1,
        )
        MachineSaleDetail.objects.create(
            source_record_id="machine-variance", business_date=date(2026, 9, 8), customer_code="C001",
            customer_name="Fekola Customer", equipment_key="E1", serial_number="SERIAL-1",
            model_name="6020", product_category="Machine Lourde", invoice_number="INVOICE-1",
            net_revenue_eur=1137.20, source_hash="machine-variance", synchronization_run=machine_run,
            source_last_seen_at=timezone.now(),
        )
        data = self.client.get(reverse("business-command-center-machine-sales-api"), {"period": "ytd"}).json()
        self.assertEqual(data["summary"]["net_revenue_eur"], 1000.0)
        self.assertEqual(data["summary"]["reconciliation_adjustment_eur"], -137.2)
        adjustments = [row for row in data["results"] if row["record_type"] == "reconciliation_adjustment"]
        self.assertEqual(len(adjustments), 1)
        self.assertEqual(adjustments[0]["other_charges_eur"], -137.2)

    def test_machine_sales_sort_uses_group_priority_then_other_then_reconciliation(self):
        def group(name, family, amount, record_type="equipment"):
            return {
                "record_type": record_type,
                "family_code": family,
                "net_revenue_eur": amount,
                "business_date": date(2026, 9, 8),
                "customer_name": name,
            }

        groups = [
            group("Accounting", "", 9999, "reconciliation_adjustment"),
            group("Other", "OTHER", 8000),
            group("Unclassified", "", 7000),
            group("Lower HMS", "HMS", 100),
            group("Higher HMS", "HMS", 500),
            group("OHT", "OHT", 9000),
        ]
        catalog = [
            {"code": "HMS", "priority": 1},
            {"code": "OHT", "priority": 3},
            {"code": "OTHER", "priority": 11},
        ]

        MachineSalesDetailService._sort_groups(groups, catalog)

        self.assertEqual(
            [item["customer_name"] for item in groups],
            ["Higher HMS", "Lower HMS", "OHT", "Unclassified", "Other", "Accounting"],
        )

    def test_machine_sales_excel_export_respects_filters(self):
        machine_run = MachineSalesSynchronizationRun.objects.create(
            status="Completed", data_through_date=date(2026, 9, 8), completed_at=timezone.now(), records_read=1,
        )
        MachineSaleDetail.objects.create(
            source_record_id="machine-export", business_date=date(2026, 9, 8), customer_code="C001",
            customer_name="Fekola Customer", equipment_key="E1", serial_number="6P300144",
            model_name="6030", family_code="HMS", brand="CAT", product_category="Machine Lourde", invoice_number="80000650",
            net_revenue_eur=10, source_hash="machine-export", synchronization_run=machine_run,
            source_last_seen_at=timezone.now(),
        )
        response = self.client.get(reverse("business-command-center-machine-sales-export-api"), {"brand": "CAT"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertGreater(len(response.content), 1000)

    def test_machine_sales_search_is_scoped_to_detail_fields(self):
        machine_run = MachineSalesSynchronizationRun.objects.create(
            status="Completed", data_through_date=date(2026, 9, 8), completed_at=timezone.now(), records_read=1,
        )
        MachineSaleDetail.objects.create(
            source_record_id="machine-search", business_date=date(2026, 9, 8), customer_code="C001",
            customer_name="IAMGOLD ESSAKANE SA SA", equipment_key="E1", serial_number="6P300144",
            model_code="6030", product_category="Machine Lourde", invoice_number="80000650", distribution_channel="On", net_revenue_eur=1,
            source_hash="machine-search", synchronization_run=machine_run, source_last_seen_at=timezone.now(),
        )
        found = self.client.get(reverse("business-command-center-machine-sales-api"), {"search": "6P300144"}).json()
        missing = self.client.get(reverse("business-command-center-machine-sales-api"), {"search": "not-found"}).json()
        self.assertEqual(found["pagination"]["count"], 1)
        self.assertEqual(missing["pagination"]["count"], 0)

    def test_invalid_custom_period_is_field_safe(self):
        response = self.client.get(reverse("business-command-center-bootstrap-api"), {"period": "custom", "start_date": "2026-09-09", "end_date": "2026-09-01"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["status"], "INVALID_CONTEXT")

    def test_command_center_requires_its_own_permission(self):
        manager = User.objects.create_user("restricted-manager", password="password")
        manager.user_permissions.add(Permission.objects.get(codename="view_business_review"))
        self.client.force_login(manager)
        self.assertEqual(self.client.get(reverse("business-command-center")).status_code, 403)
        manager.user_permissions.add(Permission.objects.get(codename="view_business_command_center"))
        manager = User.objects.get(pk=manager.pk)
        self.client.force_login(manager)
        self.assertEqual(self.client.get(reverse("business-command-center")).status_code, 200)
