from unittest.mock import patch
from pathlib import Path

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from .homepage_availability_service import HomepageAvailabilityError, HomepageAvailabilityService
from .models import (
    AIConfigSection,
    AIFilterMapping,
    AIKPITarget,
    AIMetricMapping,
    HomepageConfiguration,
    HomepageInteractionEvent,
    KnowledgeKPIDictionary,
    PlatformUser,
    PowerBIReport,
)


SAMPLE_ROWS = [
    {
        "[RowType]": "summary",
        "[Entity]": "Overall",
        "[Availability]": 0.8642,
        "[PreviousAvailability]": 0.8402,
        "[EquipmentCount]": 436,
        "[MineSiteCount]": 12,
        "[DowntimeHours]": 1234.5,
        "[LatestDate]": 46234.0,
        "[CustomerType]": "Do It For Me",
    },
    {"[RowType]": "trend", "[Entity]": "Jan 2026", "[SortKey]": "24312", "[Availability]": 0.83},
    {"[RowType]": "trend", "[Entity]": "Feb 2026", "[SortKey]": "24313", "[Availability]": 0.8642},
    {
        "[RowType]": "breakdown", "[Entity]": "Essakane", "[Availability]": 0.89,
        "[EquipmentCount]": 35, "[DowntimeHours]": 321.0,
        "[CustomerType]": "Do It For Me",
    },
    {
        "[RowType]": "breakdown", "[Entity]": "Siguiri", "[Availability]": 0.78,
        "[EquipmentCount]": 29, "[DowntimeHours]": 580.0,
        "[CustomerType]": "Do It With Me",
    },
    {"[RowType]": "option_minesite", "[Entity]": "Essakane"},
    {"[RowType]": "option_model", "[Entity]": "785"},
]


@override_settings(ENABLE_AVAILABILITY_COMMAND_CENTER_HOME="Production")
class HomepageAvailabilityCommandCenterTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_superuser("command-admin", "command@example.com", "secret")
        self.section, _ = AIConfigSection.objects.get_or_create(
            code="performance", defaults={"name": "Performance", "is_active": True}
        )
        AIMetricMapping.objects.update_or_create(
            section=self.section,
            metric_code="availability",
            defaults={
                "metric_label": "Physical Availability",
                "powerbi_measure_name": "[Avail Per Equip]",
                "is_active": True,
            },
        )
        AIMetricMapping.objects.update_or_create(
            section=self.section,
            metric_code="downtime_hours",
            defaults={
                "metric_label": "Downtime Hours",
                "powerbi_measure_name": "[DonwtimeHours]",
                "is_active": True,
            },
        )
        filters = {
            "period": ("Date", "Year Month", "Text"),
            "minesite": ("MineSiteList_MiningProd", "MineSite", "Text"),
            "model": ("EquipmentList_MiningProd", "Model", "Text"),
            "equipment": ("EquipmentList_MiningProd", "Equipment", "Text"),
            "serial_number": ("EquipmentList_MiningProd", "SN", "Text"),
            "customer": ("MineSiteList_MiningProd", "CustomerCode", "Text"),
            "family": ("EquipmentList_MiningProd", "ParentProductGroup", "Text"),
            "homepage_product_group": ("ModelList_MiningProd", "PrimeMovers", "Text"),
            "homepage_model_reference": ("ModelList_MiningProd", "Model", "Text"),
        }
        for code, (table, column, data_type) in filters.items():
            AIFilterMapping.objects.update_or_create(
                section=self.section,
                filter_code=code,
                defaults={
                    "filter_label": code.replace("_", " ").title(),
                    "powerbi_table_name": table,
                    "powerbi_column_name": column,
                    "data_type": data_type,
                    "is_active": True,
                },
            )
        self.kpi, _ = KnowledgeKPIDictionary.objects.update_or_create(
            section=self.section,
            kpi_code="availability",
            defaults={
                "kpi_name": "Physical Availability",
                "business_definition": "Validated fleet availability.",
                "formula_description": "Power BI governed measure.",
                "powerbi_measure_name": "[Avail Per Equip]",
                "unit": "%",
                "aggregation_rule": "Power BI measure",
                "default_time_grain": "Monthly",
                "powerbi_semantic_model_id": "dataset-home",
                "powerbi_workspace_id": "workspace-home",
                "source_report_name": "FPR Global DB + RLS",
                "validation_status": "Validated",
                "is_active": True,
            },
        )
        PowerBIReport.objects.update_or_create(
            report_id="report-home",
            defaults={
                "section": self.section,
                "workspace_id": "workspace-home",
                "report_name": "FPR Global DB + RLS",
                "display_name": "Fleet Performance Report",
                "semantic_model_id": "dataset-home",
                "validation_status": "Validated",
                "is_active": True,
            },
        )
        AIKPITarget.objects.update_or_create(
            section=self.section,
            metric_code="availability",
            defaults={
                "target": 0.90,
                "warning_threshold": 0.85,
                "critical_threshold": 0.80,
                "unit": "%",
                "is_active": True,
            },
        )
        HomepageConfiguration.objects.update_or_create(
            code="availability-command-center",
            defaults={"cache_duration_seconds": 300, "active": True},
        )

    def service(self):
        return HomepageAvailabilityService(self.user)

    def test_default_request_is_ytd_overall(self):
        request = self.service().request_from_params({})
        self.assertEqual(request.period, "ytd")
        self.assertEqual(request.breakdown, "overall")

    def test_dax_uses_governed_measure_and_latest_nonblank_date(self):
        service = self.service()
        dax = service.build_dax(service.request_from_params({}), {})
        self.assertIn("[Avail Per Equip]", dax)
        self.assertIn("MAXX", dax)
        self.assertIn("NOT ISBLANK", dax)
        self.assertNotIn("TODAY()", dax)
        self.assertIn("VAR __LatestDataDate", dax)
        self.assertIn("VAR __LatestDate = EOMONTH(__LatestDataDate, 0)", dax)
        self.assertIn("DATE(YEAR(__LatestDate), 1, 1)", dax)
        self.assertIn("'MineSiteList_MiningProd'[Focus]", dax)
        self.assertIn('TREATAS({"Yes"}', dax)
        self.assertIn("'MineSiteList_MiningProd'[CustomerType]", dax)
        self.assertIn("'ModelList_MiningProd'[PrimeMovers]", dax)
        self.assertIn('TREATAS({"HMS", "LMT", "LWL", "OHT"}', dax)
        self.assertIn("VAR __AllowedModels", dax)
        self.assertIn("VAR __ModelOptionsBase", dax)
        self.assertIn("NOT ISBLANK([OptionAvailability])", dax)
        self.assertIn("VAR __EquipmentOptionsBase", dax)
        self.assertIn('"RowType", "option_equipment"', dax)

    def test_model_breakdown_is_restricted_to_homepage_product_groups(self):
        service = self.service()
        request = service.request_from_params({"breakdown": "model"})
        dax = service.build_dax(request, {})
        self.assertGreaterEqual(
            dax.count("TREATAS(__AllowedModels, 'EquipmentList_MiningProd'[Model])"),
            2,
        )

    def test_selected_model_is_restricted_to_homepage_product_groups(self):
        service = self.service()
        request = service.request_from_params({"model": "785"})
        dax = service.build_dax(request, {"model": ["785"]})
        self.assertGreaterEqual(
            dax.count("TREATAS(__AllowedModels, 'EquipmentList_MiningProd'[Model])"),
            2,
        )

    def test_last_12_months_is_anchored_to_latest_date(self):
        service = self.service()
        request = service.request_from_params({"period": "last_12_months"})
        dax = service.build_dax(request, {})
        self.assertIn("EOMONTH(__LatestDate, -12) + 1", dax)
        self.assertIn("EOMONTH(__LatestDate, -24) + 1", dax)

    def test_month_key_is_expanded_to_month_end_for_ytd(self):
        service = self.service()
        dax = service.build_dax(service.request_from_params({"period": "ytd"}), {})
        self.assertIn("VAR __LatestDate = EOMONTH(__LatestDataDate, 0)", dax)
        self.assertIn("DATESBETWEEN", dax)

    @patch.object(HomepageAvailabilityService, "_refresh_metadata", return_value=("2026-08-20 04:39 AM", "Completed"))
    @patch("reports.homepage_availability_service.execute_dax_via_flow")
    def test_normalized_response_contains_target_trend_and_rankings(self, execute, _refresh):
        execute.return_value = {"firstTableRows": SAMPLE_ROWS}
        result = self.service().get(self.service().request_from_params({}))
        self.assertEqual(result["availability"]["formatted_value"], "86.42%")
        self.assertEqual(result["availability"]["target_formatted"], "85.00%")
        self.assertEqual(result["availability"]["customer_type"], "Do It For Me")
        self.assertEqual(result["availability"]["comparison"]["delta_points"], 2.4)
        self.assertEqual(result["context"]["start_date"], "2026-01-01")
        self.assertEqual(len(result["trend"]), 2)
        self.assertEqual(result["top_performers"][0]["entity"], "Essakane")
        self.assertEqual(result["bottom_performers"][0]["entity"], "Siguiri")
        self.assertEqual(result["breakdown"][0]["target_formatted"], "85.00%")

    def test_customer_type_targets_are_governed_by_business_rule(self):
        service = self.service()
        self.assertEqual(service._customer_type_target("Do It For Me"), 0.85)
        self.assertEqual(service._customer_type_target("do it with me"), 0.80)
        self.assertEqual(service._customer_type_target("  Do It Myself  "), 0.75)
        self.assertIsNone(service._customer_type_target("Unknown"))

    @patch.object(HomepageAvailabilityService, "_refresh_metadata", return_value=("", "Unavailable"))
    @patch("reports.homepage_availability_service.execute_dax_via_flow")
    def test_out_of_range_availability_is_flagged_not_presented_as_a_kpi(self, execute, _refresh):
        execute.return_value = {
            "firstTableRows": [
                {"[RowType]": "summary", "[Availability]": -18.1788, "[LatestDate]": 46023.0},
                {"[RowType]": "breakdown", "[Entity]": "JRP01975", "[Availability]": -18.1788},
            ]
        }
        result = self.service().get(self.service().request_from_params({"breakdown": "equipment"}))
        self.assertIsNone(result["availability"]["raw_value"])
        self.assertEqual(result["availability"]["source_raw_value"], -18.1788)
        self.assertEqual(result["availability"]["quality_status"], "out_of_range")
        self.assertEqual(result["availability"]["formatted_value"], "Invalid data")
        self.assertEqual(result["breakdown"][0]["status"], "data_quality_issue")
        self.assertEqual(result["top_performers"], [])
        self.assertTrue(result["warnings"])

    @patch.object(HomepageAvailabilityService, "_refresh_metadata", return_value=("", "Unavailable"))
    @patch("reports.homepage_availability_service.execute_dax_via_flow")
    def test_cache_reuses_unchanged_user_context(self, execute, _refresh):
        execute.return_value = {"firstTableRows": SAMPLE_ROWS}
        service = self.service()
        service.get(service.request_from_params({}))
        result = service.get(service.request_from_params({}))
        self.assertEqual(execute.call_count, 1)
        self.assertTrue(result["meta"]["cached"])

    def test_user_scope_cannot_be_overridden(self):
        user = User.objects.create_user("viewer", "viewer@example.com", "secret")
        PlatformUser.objects.create(
            django_user=user,
            azure_ad_id="viewer-object",
            user_principal_name="viewer@example.com",
            display_name="Viewer",
            can_access_reporting=True,
            business_performance_scope={"minesite": ["Essakane"], "rls_role": "SiteViewer"},
        )
        service = HomepageAvailabilityService(user)
        scope, _, _ = service._scope()
        with self.assertRaises(HomepageAvailabilityError) as raised:
            service._merge_filters(scope, {"minesite": "Fekola"})
        self.assertEqual(raised.exception.status, 403)

    @patch.object(HomepageAvailabilityService, "_refresh_metadata", return_value=("", "Unavailable"))
    @patch("reports.homepage_availability_service.execute_dax_via_flow")
    def test_api_returns_normalized_command_center_contract(self, execute, _refresh):
        execute.return_value = {"firstTableRows": SAMPLE_ROWS}
        self.client.force_login(self.user)
        response = self.client.get(reverse("homepage-availability-api"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["context"]["period_code"], "ytd")
        self.assertIn("data_quality", payload)
        self.assertIn("available_actions", payload)

    def test_reporting_permission_is_required_for_api(self):
        user = User.objects.create_user("no-reporting", "none@example.com", "secret")
        PlatformUser.objects.create(
            django_user=user,
            azure_ad_id="none-object",
            user_principal_name="none@example.com",
            display_name="No Reporting",
        )
        self.client.force_login(user)
        response = self.client.get(reverse("homepage-availability-api"))
        self.assertEqual(response.status_code, 403)

    def test_homepage_renders_command_center_without_powerbi_iframe(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Fleet Availability Command Center")
        self.assertContains(response, ">Command Center</span>")
        self.assertContains(response, 'aria-current="page"')
        self.assertContains(response, "homepage_command_center.js")
        self.assertNotContains(response, "Performance detail")
        self.assertContains(response, "data-breakdown-section")
        self.assertContains(response, 'data-filter-field="minesite"')
        self.assertContains(response, 'data-filter-field="model"')
        self.assertContains(response, 'data-filter-field="equipment"')
        self.assertContains(response, 'data-filter="equipment"')
        self.assertNotContains(response, 'data-breakdown-control')
        self.assertNotContains(response, '>Analysis<')
        self.assertNotContains(response, "Serial Number")
        self.assertNotContains(response, "powerbi.embed")
        self.assertNotContains(response, "<iframe")

    def test_control_bar_uses_named_responsive_grid_without_negative_margins(self):
        css = Path(__file__).parent.joinpath("static/reports/homepage_command_center.css").read_text(
            encoding="utf-8"
        )
        self.assertIn("grid-template-areas", css)
        self.assertIn('"period minesite model equipment reset"', css)
        self.assertNotIn(".analysis-group", css)
        self.assertIn("@media (max-width: 1599px)", css)
        self.assertIn("@media (max-width: 1099px)", css)
        self.assertIn("@media (max-width: 699px)", css)
        self.assertNotIn(".analysis-controls { margin:", css)
        self.assertIn(".context-controls {\n    display: contents;", css)

    def test_equipment_requiring_attention_section_is_not_rendered(self):
        javascript = Path(__file__).parent.joinpath(
            "static/reports/homepage_command_center.js"
        ).read_text(encoding="utf-8")
        self.assertNotIn("Equipment requiring attention", javascript)
        self.assertIn(
            'state.breakdown === "overall" || state.breakdown === "equipment"',
            javascript,
        )

    def test_trend_chart_renders_availability_value_labels(self):
        javascript = Path(__file__).parent.joinpath(
            "static/reports/homepage_command_center.js"
        ).read_text(encoding="utf-8")
        css = Path(__file__).parent.joinpath(
            "static/reports/homepage_command_center.css"
        ).read_text(encoding="utf-8")

        self.assertIn('class="trend-value-label"', javascript)
        self.assertIn("point.formatted_value", javascript)
        self.assertIn(".trend-value-label", css)
        self.assertIn("paint-order: stroke fill", css)

    def test_trend_chart_labels_configured_target(self):
        javascript = Path(__file__).parent.joinpath(
            "static/reports/homepage_command_center.js"
        ).read_text(encoding="utf-8")
        css = Path(__file__).parent.joinpath(
            "static/reports/homepage_command_center.css"
        ).read_text(encoding="utf-8")

        self.assertIn('class="trend-target-label"', javascript)
        self.assertIn("`Target ${(Number(target) * 100).toFixed(1)}%`", javascript)
        self.assertIn(".trend-target-label", css)

    def test_homepage_has_branded_initial_loader(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        javascript = Path(__file__).parent.joinpath(
            "static/reports/homepage_command_center.js"
        ).read_text(encoding="utf-8")
        css = Path(__file__).parent.joinpath(
            "static/reports/homepage_command_center.css"
        ).read_text(encoding="utf-8")

        self.assertContains(response, "data-brand-loader")
        self.assertContains(response, "neemba-cat-logo.jpg")
        self.assertContains(response, "Preparing your command center")
        self.assertIn("dismissBrandLoader", javascript)
        self.assertIn("@keyframes neemba-loader-fan", css)
        self.assertIn("inset: 0 0 0 var(--sidebar-width)", css)
        self.assertIn("width: min(210px, 70vw)", css)

    def test_command_center_ui_copy_is_english_only(self):
        template = Path(__file__).parent.joinpath("templates/reports/dashboard.html").read_text(
            encoding="utf-8"
        )
        javascript = Path(__file__).parent.joinpath(
            "static/reports/homepage_command_center.js"
        ).read_text(encoding="utf-8")
        rendered_copy = template + javascript
        forbidden_french_copy = (
            "Période",
            "Analyse de la performance",
            "Connexion au modèle",
            "Actualisation en attente",
            "Tous les sites",
            "Tous les modèles",
            "Tous les équipements",
            "Recherche de la dernière date",
            "Power BI indisponible",
        )
        for label in forbidden_french_copy:
            with self.subTest(label=label):
                self.assertNotIn(label, rendered_copy)

    @override_settings(ENABLE_AVAILABILITY_COMMAND_CENTER_HOME="Disabled")
    def test_feature_flag_preserves_legacy_dashboard(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Operational console")
        self.assertNotContains(response, "Availability Command Center")

    def test_interaction_endpoint_accepts_only_governed_context(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("homepage-interaction-api"),
            data={
                "event_type": "period_change",
                "context": {"period": "ytd", "secret": "do-not-store"},
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        event = HomepageInteractionEvent.objects.get()
        self.assertEqual(event.context_json, {"period": "ytd"})
