from datetime import date

from django.contrib.auth.models import Permission, User
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .business_command_center_service import BusinessRevenuePeriodService
from .models import MappingPublication, MappingSynchronizationRun, RevenueSourceSnapshot


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
