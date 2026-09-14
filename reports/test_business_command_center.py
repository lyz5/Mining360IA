from datetime import date

from django.contrib.auth.models import Permission, User
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .business_command_center_service import BusinessRevenuePeriodService
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
        custom = BusinessRevenuePeriodService.resolve(latest, "custom", "2026-02-01", "2026-02-28", "previous_equivalent_period")
        self.assertEqual((custom["comparison_start_date"], custom["comparison_end_date"]), (date(2026, 1, 4), date(2026, 1, 31)))


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

    def _revenue(self, record_id, account, lob, business_date, amount):
        return RevenueSourceSnapshot.objects.create(
            synchronization_run=self.run, source_record_id=record_id, source_account_code=account,
            source_account_name="Fekola Customer", business_date=business_date, source_lob=lob, lob=lob,
            division="MI", period_year=business_date.year, revenue_eur=amount, revenue_ytd_eur=amount,
            source_hash=record_id, source_last_seen_at=timezone.now(),
        )

    def test_page_and_bootstrap_load_without_published_mapping(self):
        self.assertEqual(self.client.get(reverse("business-command-center")).status_code, 200)
        response = self.client.get(reverse("business-command-center-bootstrap-api"))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["mode"], "unmapped_business_line")
        self.assertEqual(data["hero"]["revenue"], 3500.0)
        self.assertEqual(sum(item["revenue"] for item in data["business_lines"]), 3500.0)
        self.assertEqual(data["reconciliation"]["status"], "RECONCILED")
        self.assertEqual(data["context"]["end_date"], "2026-09-08")
        self.assertEqual(data["sales_review"]["summary"]["actual_revenue"], 3500.0)
        self.assertEqual(data["sales_review"]["summary"]["comparison_revenue"], 1750.0)
        self.assertEqual(data["sales_review"]["budget"]["status"], "NOT_AVAILABLE")
        self.assertEqual(data["sales_review"]["firm_orders"]["status"], "NOT_AVAILABLE")

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
                "source_account_codes": ["C001"], "business_country": "Mali",
                "key_account_id": "K1", "key_account_name": "B2Gold",
            }]},
        )
        data = self.client.get(reverse("business-command-center-bootstrap-api"), {"business_line": "parts"}).json()
        self.assertTrue(data["mapping_ready"])
        self.assertEqual(data["dimensions"]["customers"][0]["revenue"], 2000.0)
        self.assertEqual(data["dimensions"]["countries"][0]["revenue"], 2000.0)
        self.assertEqual(data["dimensions"]["key_accounts"][0]["revenue"], 2000.0)
        self.assertEqual(data["sales_review"]["by_country"][0]["name"], "Mali")
        self.assertEqual(data["sales_review"]["by_customer"][0]["name"], "Fekola Canonical")

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
        self.assertEqual(data["filter_options"]["key_accounts"][0]["name"], "CORICA")

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
