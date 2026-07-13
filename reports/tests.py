import json
import os

os.environ["MINING360_SQL_CONFIG_STORE"] = "0"

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .business_performance_service import BusinessPerformanceService, MappingNotConfigured
from .models import (
    AIConfigSection,
    AIFilterMapping,
    AIMetricMapping,
    BusinessPerformanceConfig,
    BusinessPerformanceMapping,
    KPIPageMapping,
    PlatformUser,
    PowerBIPage,
    PowerBIReport,
)
from .powerbi_interaction_service import resolve_navigation, validate_interaction_intent


class BusinessPerformanceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("bp-admin", password="test", is_staff=True)
        PlatformUser.objects.create(
            azure_ad_id="bp-admin", user_principal_name="bp-admin@example.com",
            display_name="BP Admin", django_user=self.user, is_active=True,
            is_platform_admin=True, can_access_reporting=True,
            business_performance_role="Administrator",
        )
        BusinessPerformanceConfig.objects.get_or_create(name="Business Performance")
        required = {
            "active_fleet": ("", "Fleet", "measure"),
            "parts_revenue": ("", "CA Parts", "measure"),
            "prime_revenue": ("", "CA Prime", "measure"),
            "total_revenue": ("", "Total CA", "measure"),
            "parts_revenue_per_fleet": ("", "Parts/Fleet", "measure"),
            "customer": ("Customer", "Customer Name", "column"),
            "year": ("Date", "Year", "column"),
        }
        for order, (logical_name, values) in enumerate(required.items()):
            table, object_name, object_type = values
            BusinessPerformanceMapping.objects.update_or_create(
                logical_name=logical_name,
                defaults={
                    "display_name": logical_name.replace("_", " ").title(),
                    "category": "metric" if object_type == "measure" else "filter",
                    "object_type": object_type, "table_name": table,
                    "object_name": object_name, "display_order": order, "is_active": True,
                },
            )
        self.client.force_login(self.user)

    def test_business_performance_page_is_disabled(self):
        response = self.client.get(reverse("business-performance"))
        self.assertEqual(response.status_code, 404)

    def test_controlled_dax_uses_configured_objects(self):
        service = BusinessPerformanceService(self.user)
        dax = service._summarize(
            ["customer"], ["active_fleet", "parts_revenue"],
            {"year": ["2026"], "customer": ["Mota-Engil Côte d’Ivoire"]}, 20,
            "parts_revenue",
        )
        self.assertIn("'Customer'[Customer Name]", dax)
        self.assertIn("[CA Parts]", dax)
        self.assertIn('Mota-Engil Côte d’Ivoire', dax)
        self.assertNotIn("EVALUATE EVALUATE", dax)

    def test_missing_mapping_is_explicit(self):
        BusinessPerformanceMapping.objects.filter(logical_name="customer").update(table_name="", object_name="")
        with self.assertRaises(MappingNotConfigured):
            BusinessPerformanceService(self.user).object_ref("customer")

    def test_admin_can_update_configuration(self):
        mapping = BusinessPerformanceMapping.objects.get(logical_name="customer")
        response = self.client.post(
            reverse("business-performance-config-api"),
            data=json.dumps({"top_n_default": 30, "mappings": [{"id": mapping.id, "table_name": "Customers", "object_name": "Name"}]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)


class BusinessPerformanceAccessTests(TestCase):
    def test_user_without_business_role_is_denied(self):
        user = User.objects.create_user("viewer", password="test")
        PlatformUser.objects.create(
            azure_ad_id="viewer", user_principal_name="viewer@example.com", display_name="Viewer",
            django_user=user, is_active=True, can_access_reporting=True,
        )
        self.client.force_login(user)
        response = self.client.get(reverse("business-performance"))
        self.assertEqual(response.status_code, 404)


class PowerBIInteractionTests(TestCase):
    def setUp(self):
        self.section = AIConfigSection.objects.create(name="Performance Test", code="performance_test")
        AIMetricMapping.objects.create(
            section=self.section, metric_code="availability", metric_label="Availability",
            powerbi_measure_name="[Availability]",
        )
        AIFilterMapping.objects.create(
            section=self.section, filter_code="minesite", filter_label="Minesite",
            powerbi_table_name="MineSite", powerbi_column_name="MineSiteName", data_type="Text",
        )
        self.report = PowerBIReport.objects.create(
            section=self.section, workspace_id="workspace", report_id="configured-report",
            report_name="Fleet Performance", display_name="Fleet Performance",
            semantic_model_id="dataset", embed_url="https://app.powerbi.com/reportEmbed",
            validation_status="Validated",
        )
        self.page = PowerBIPage.objects.create(
            report=self.report, section=self.section, page_internal_name="ReportSection2",
            page_display_name="Fleet Overview", validation_status="Validated",
        )
        KPIPageMapping.objects.create(
            section=self.section, metric_code="availability", report=self.report,
            page=self.page, is_default=True,
        )

    def intent(self):
        return {
            "section": self.section.code,
            "intent_type": "single_kpi",
            "metric": "availability",
            "filters": {"minesite": "Fekola"},
            "navigation": {"open_report": True, "open_page": True, "focus_visual": False},
        }

    def test_resolver_uses_only_configured_identifiers(self):
        intent = self.intent()
        intent["report_id"] = "attacker-controlled-report"
        intent["page_internal_name"] = "attacker-controlled-page"
        navigation = resolve_navigation(intent)
        self.assertEqual(navigation["report_id"], "configured-report")
        self.assertEqual(navigation["page_internal_name"], "ReportSection2")

    def test_unconfigured_filter_is_rejected(self):
        intent = self.intent()
        intent["filters"]["unknown_filter"] = "value"
        valid, errors, _ = validate_interaction_intent(intent)
        self.assertFalse(valid)
        self.assertTrue(any("unknown_filter" in error for error in errors))

    def test_unvalidated_report_is_not_used_in_production(self):
        self.report.validation_status = "To Review"
        self.report.save()
        valid, errors, _ = validate_interaction_intent(self.intent())
        self.assertFalse(valid)
        self.assertTrue(any("validated Power BI report" in error for error in errors))
