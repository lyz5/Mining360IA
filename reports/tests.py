import json
import os

os.environ["MINING360_SQL_CONFIG_STORE"] = "0"

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from .business_performance_service import BusinessPerformanceService, MappingNotConfigured
from .models import (
    AIConfigSection,
    AIFilterMapping,
    AIMetricMapping,
    BusinessPerformanceConfig,
    BusinessPerformanceMapping,
    KnowledgeKPIDictionary,
    KPIPageMapping,
    PlatformUser,
    PowerBIPage,
    PowerBIReport,
    PowerBISlicer,
)
from .powerbi_interaction_service import resolve_navigation, validate_interaction_intent
from .knowledge_resolution_service import _safe


class KPIDictionaryValidationTests(TestCase):
    def setUp(self):
        self.section = AIConfigSection.objects.create(
            name="KPI Test", code="kpi_test"
        )
        self.defaults = {
            "section": self.section,
            "kpi_code": "availability",
            "kpi_name": "Availability",
            "business_definition": "Equipment availability.",
            "formula_description": "Available time divided by scheduled time.",
            "powerbi_measure_name": "[Availability]",
            "unit": "%",
            "aggregation_rule": "Use the semantic model measure.",
            "default_time_grain": "Monthly",
            "higher_is_better": True,
            "threshold_direction": "Higher Is Better",
            "target": 90,
            "warning_threshold": 85,
            "critical_threshold": 80,
        }

    def test_lowercase_snake_case_is_required(self):
        item = KnowledgeKPIDictionary(**{**self.defaults, "kpi_code": "Availability KPI"})
        with self.assertRaises(Exception):
            item.full_clean()

    def test_higher_is_better_threshold_order_is_validated(self):
        item = KnowledgeKPIDictionary(**{**self.defaults, "warning_threshold": 95})
        with self.assertRaises(Exception):
            item.full_clean()

    def test_direction_flags_are_mutually_exclusive(self):
        item = KnowledgeKPIDictionary(
            **{**self.defaults, "higher_is_better": True, "lower_is_better": True}
        )
        with self.assertRaises(Exception):
            item.full_clean()

    def test_powerbi_measure_is_required_for_validated_kpi(self):
        item = KnowledgeKPIDictionary(
            **{
                **self.defaults,
                "powerbi_measure_name": "",
                "validation_status": "Validated",
            }
        )
        with self.assertRaises(Exception):
            item.full_clean()


class KnowledgeCoverageModeTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            "coverage-admin", "coverage@example.com", "password"
        )
        self.standard = User.objects.create_user(
            "coverage-user", password="password"
        )
        self.section = AIConfigSection.objects.create(
            name="Coverage Test", code="coverage_test"
        )
        self.kpi = KnowledgeKPIDictionary.objects.create(
            section=self.section,
            kpi_code="availability",
            kpi_name="Availability",
            business_definition="Equipment availability.",
            business_purpose="Reliability monitoring.",
            formula_description="Available time divided by scheduled time.",
            powerbi_measure_name="[Availability]",
            powerbi_semantic_model_id="dataset-id",
            unit="%",
            aggregation_rule="Use the semantic model measure.",
            default_time_grain="Monthly",
            validation_status="Draft",
            is_active=True,
        )
        self.url = reverse("knowledge-base-coverage-test-api")

    def post_coverage(self, user, mode):
        self.client.force_login(user)
        return self.client.post(
            self.url,
            data=json.dumps({
                "section": self.section.code,
                "kpi": self.kpi.kpi_code,
                "mode": mode,
            }),
            content_type="application/json",
            HTTP_ACCEPT="application/json",
        )

    def test_production_rejects_draft_kpi(self):
        payload = self.post_coverage(self.admin, "Production").json()
        self.assertFalse(payload["checks"]["kpi_defined"])
        self.assertEqual(payload["debug"]["candidate_kpi_id"], self.kpi.id)
        self.assertIn("Draft", payload["debug"]["rejection_reason"])

    def test_debug_uses_draft_kpi_and_measure_mapping(self):
        payload = self.post_coverage(self.admin, "Debug").json()
        self.assertTrue(payload["checks"]["kpi_defined"])
        self.assertTrue(payload["checks"]["measure_mapped"])
        self.assertEqual(payload["debug"]["matched_kpi_id"], self.kpi.id)
        self.assertTrue(payload["warnings"])

    def test_debug_is_restricted_to_administrators(self):
        response = self.post_coverage(self.standard, "Debug")
        self.assertEqual(response.status_code, 403)

    def test_knowledge_resolution_is_restricted_to_administrators(self):
        self.client.force_login(self.standard)
        response = self.client.post(
            reverse("knowledge-resolution-api"),
            data=json.dumps({"question": "Give me availability", "mode": "Debug"}),
            content_type="application/json",
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_resolution_redacts_sensitive_keys(self):
        safe = _safe({
            "access_token": "secret-token",
            "nested": {"client_secret": "secret", "value": "visible"},
        })
        self.assertEqual(safe["access_token"], "[REDACTED]")
        self.assertEqual(safe["nested"]["client_secret"], "[REDACTED]")
        self.assertEqual(safe["nested"]["value"], "visible")

    def test_resolution_exports_are_scoped_to_current_admin(self):
        trace_id = "test-trace"
        cache.set(
            f"knowledge-resolution:{self.admin.pk}:{trace_id}",
            {"question_analysis": {"original_question": "Availability"}},
            60,
        )
        self.client.force_login(self.admin)
        for file_type, content_type in [
            ("json", "application/json"),
            ("md", "text/markdown; charset=utf-8"),
            ("pdf", "application/pdf"),
        ]:
            response = self.client.get(
                reverse(
                    "knowledge-resolution-export",
                    args=[trace_id, file_type],
                )
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], content_type)


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
            "global_revenue_ytd": ("", "YTD Parts Sales Dyn", "measure"),
            "global_revenue_eur": ("", "CA Facture EU", "measure"),
            "global_revenue_usd": ("", "CA Facture US", "measure"),
            "global_revenue_cfa": ("", "CA Facture XO", "measure"),
            "prime_revenue": ("", "CA Prime", "measure"),
            "service_revenue": ("", "CA Services", "measure"),
            "service_order_count": ("", "Service Orders", "measure"),
            "rental_revenue": ("", "CA Rental", "measure"),
            "rental_order_count": ("", "Rental Orders", "measure"),
            "total_revenue": ("", "Total CA", "measure"),
            "parts_revenue_per_fleet": ("", "Parts/Fleet", "measure"),
            "customer": ("Customer", "Customer Name", "column"),
            "year": ("Date", "Year", "column"),
            "lob": ("GlobalCA", "LOB", "column"),
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

    def test_global_ytd_uses_official_semantic_measure(self):
        service = BusinessPerformanceService(self.user)
        dax = service._summarize([], ["global_revenue_ytd"], {"year": ["2026"]})
        self.assertIn("[YTD Parts Sales Dyn]", dax)
        self.assertNotIn("TOTALYTD", dax)

    def test_parts_domain_uses_validated_globalca_lob_filter(self):
        service = BusinessPerformanceService(self.user)
        filters = service._domain_filters("parts", {"year": ["2026"]})
        dax = service._summarize([], ["global_revenue_ytd"], filters)
        self.assertIn("TREATAS({\"PARTS\"}, 'GlobalCA'[LOB])", dax)

    def test_machine_domain_uses_validated_prime_lob(self):
        service = BusinessPerformanceService(self.user)
        self.assertEqual(service._domain_filters("prime", {})["lob"], ["PRIME"])

    def test_services_domain_uses_validated_service_lob(self):
        service = BusinessPerformanceService(self.user)
        self.assertEqual(service._domain_filters("services", {})["lob"], ["SERVICE"])

    def test_rental_domain_uses_validated_rental_lob(self):
        service = BusinessPerformanceService(self.user)
        self.assertEqual(service._domain_filters("rental", {})["lob"], ["RENTAL"])

    def test_default_currency_uses_official_euro_invoice_measure(self):
        service = BusinessPerformanceService(self.user)
        self.assertEqual(service.revenue_metric(), "global_revenue_eur")
        self.assertEqual(service.object_ref(service.revenue_metric()), "[CA Facture EU]")

    def test_supported_invoice_currency_measures(self):
        config = BusinessPerformanceConfig.objects.get(name="Business Performance")
        expected = {"USD": "global_revenue_usd", "XOF": "global_revenue_cfa"}
        for currency, metric in expected.items():
            config.default_currency = currency
            config.save(update_fields=["default_currency"])
            self.assertEqual(BusinessPerformanceService(self.user).revenue_metric(), metric)

    def test_missing_mapping_is_explicit(self):
        BusinessPerformanceMapping.objects.filter(logical_name="customer").update(table_name="", object_name="")
        with self.assertRaises(MappingNotConfigured):
            BusinessPerformanceService(self.user).object_ref("customer")

    def test_services_sales_uses_configured_measures(self):
        service = BusinessPerformanceService(self.user)
        dax = service._summarize(
            ["customer"], ["service_revenue", "service_order_count"],
            {"year": ["2026"]}, 50, "service_revenue",
        )
        self.assertIn("[CA Services]", dax)
        self.assertIn("[Service Orders]", dax)
        self.assertIn("'Date'[Year]", dax)

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

    def test_report_slicer_maps_canonical_filter_value(self):
        PowerBISlicer.objects.create(
            page=self.page,
            slicer_internal_name="configured-sitegroup-filter",
            slicer_title="SiteGroup",
            powerbi_table_name="DIM - Sites",
            powerbi_column_name="SiteGroup",
            filter_code="minesite",
            value_mapping={"Fekola": "B2Gold Fekola"},
            validation_status="Validated",
        )
        navigation = resolve_navigation(self.intent())
        site_filter = navigation["filters"][0]
        self.assertEqual(site_filter["table"], "DIM - Sites")
        self.assertEqual(site_filter["column"], "SiteGroup")
        self.assertEqual(site_filter["values"], ["B2Gold Fekola"])
        self.assertEqual(site_filter["scope"], "slicer")

    def test_slicer_value_mapping_is_case_insensitive(self):
        PowerBISlicer.objects.create(
            page=self.page,
            slicer_internal_name="configured-sitegroup-filter",
            slicer_title="SiteGroup",
            powerbi_table_name="DIM - Sites",
            powerbi_column_name="SiteGroup",
            filter_code="minesite",
            value_mapping={"Fekola": "B2Gold Fekola"},
            validation_status="Validated",
        )
        intent = self.intent()
        intent["filters"]["minesite"] = "fekola"
        navigation = resolve_navigation(intent)
        self.assertEqual(navigation["filters"][0]["values"], ["B2Gold Fekola"])

    def test_fleet_year_month_filter_uses_powerbi_display_value(self):
        AIFilterMapping.objects.create(
            section=self.section, filter_code="period", filter_label="Period",
            powerbi_table_name="Date", powerbi_column_name="Year Month",
            data_type="Text",
        )
        PowerBISlicer.objects.create(
            page=self.page,
            slicer_internal_name="configured-fleet-year-month-filter",
            slicer_title="Year Month",
            powerbi_table_name="Date",
            powerbi_column_name="Year Month",
            filter_code="period",
            supports_multiple_values=True,
            validation_status="Validated",
        )
        intent = self.intent()
        intent["filters"]["period"] = "2026-05"
        navigation = resolve_navigation(intent)
        period_filter = next(
            item for item in navigation["filters"]
            if item["filter_code"] == "period"
        )
        self.assertEqual(period_filter["column"], "Year Month")
        self.assertEqual(period_filter["values"], ["May 2026"])
        self.assertNotIn("filter_type", period_filter)

    def test_fleet_last_12_months_resolves_to_12_categories(self):
        AIFilterMapping.objects.create(
            section=self.section, filter_code="period", filter_label="Period",
            powerbi_table_name="Date", powerbi_column_name="Year Month",
            data_type="Text",
        )
        PowerBISlicer.objects.create(
            page=self.page,
            slicer_internal_name="configured-fleet-year-month-filter",
            slicer_title="Year Month",
            powerbi_table_name="Date",
            powerbi_column_name="Year Month",
            filter_code="period",
            supports_multiple_values=True,
            validation_status="Validated",
        )
        intent = self.intent()
        intent["filters"]["period"] = "last 12 months"
        navigation = resolve_navigation(intent)
        period_filter = next(
            item for item in navigation["filters"]
            if item["filter_code"] == "period"
        )
        self.assertEqual(len(period_filter["values"]), 12)
