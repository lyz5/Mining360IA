from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings
from unittest.mock import Mock, patch

from .machine_performance_intent_service import (
    detect_machine_performance_intent,
    enrich_machine_performance_intent,
)
from .machine_performance_response_service import (
    MachinePerformanceResponsePlanningService,
    MachinePerformanceResponseTemplateResolver,
    adaptive_performance_responses_enabled,
)
from .models import AIIntentResponseTemplateMapping, AIResponseTemplate
from .power_automate import execute_dax_via_flow


class MachinePerformanceIntentTests(SimpleTestCase):
    def test_required_business_intents_have_priority_over_metric_words(self):
        cases = {
            "Essakane availability May 2026": "single_kpi",
            "Show the top downtime drivers at Essakane in May 2026.": "downtime_drivers",
            "Compare availability between Essakane and Fekola in May 2026.": "entity_comparison",
            "Show the monthly availability trend for Essakane over the last 12 months.": "trend_analysis",
            "Which 10 machines have the lowest availability at Essakane?": "ranking",
            "Show me equipment serial XYZ123.": "equipment_detail",
            "Why did availability decrease at Essakane in May 2026?": "root_cause_analysis",
            "Show downtime events for Power Train at Essakane.": "downtime_events",
            "Summarize maintenance comments for Engine downtime at Essakane.": "comment_analysis",
            "Show the SMCS breakdown for Power Train.": "smcs_breakdown",
        }
        for question, expected in cases.items():
            with self.subTest(question=question):
                self.assertEqual(detect_machine_performance_intent(question), expected)

    def test_period_comparison_is_not_entity_comparison(self):
        self.assertEqual(
            detect_machine_performance_intent("Compare May 2026 with April 2026."),
            "period_comparison",
        )

    @patch("reports.intent_extractor_service.build_section_catalog")
    def test_downtime_hours_phrase_selects_hours_measure(self, catalog):
        catalog.return_value = {"sections": [{"metrics": [
            {"metric_code": "downtime", "metric_label": "Downtime"},
            {"metric_code": "downtime_hours", "metric_label": "Downtime Hours"},
        ], "filters": []}]}
        from .intent_extractor_service import _detect_metric
        self.assertEqual(
            _detect_metric("nombres d'heures de downtimes des 777", "performance"),
            "downtime_hours",
        )

    def test_scope_and_query_alias_are_enriched(self):
        intent = enrich_machine_performance_intent({
            "metric": "availability",
            "filters": {"period": "2026-05"},
            "comparison": {"minesite": ["Essakane", "Fekola"]},
        }, "Compare availability between Essakane and Fekola")
        self.assertEqual(intent["intent_type"], "entity_comparison")
        self.assertEqual(intent["scope_type"], "multiple_minesites")
        self.assertEqual(intent["query_intent_type"], "comparison")


class MachinePerformancePlanningTests(TestCase):
    def setUp(self):
        self.planner = MachinePerformanceResponsePlanningService()

    def test_single_kpi_uses_one_primary_query_without_diagnostics(self):
        plan = self.planner.build_query_plan({
            "intent_type": "single_kpi", "metric": "availability",
            "primary_metric": "availability",
        })
        self.assertTrue(plan["execute_primary_metric"])
        self.assertFalse(plan["execute_downtime_diagnostics"])

    def test_downtime_drivers_execute_diagnostics_without_forcing_availability(self):
        plan = self.planner.build_query_plan({
            "intent_type": "downtime_drivers", "metric": None, "primary_metric": None,
        })
        self.assertFalse(plan["execute_primary_metric"])
        self.assertTrue(plan["execute_downtime_diagnostics"])

    def test_validated_database_mapping_overrides_default(self):
        template = AIResponseTemplate.objects.create(
            code="comparison_compact_test", name="Comparison compact",
            component_order_json=["comparison_table", "contextual_actions"],
            validation_status="Validated", active=True,
        )
        AIIntentResponseTemplateMapping.objects.create(
            intent_type="entity_comparison", scope_type="multiple_minesites",
            response_template=template, validation_status="Validated", active=True,
            priority=500,
        )
        resolved = MachinePerformanceResponseTemplateResolver().resolve({
            "intent_type": "entity_comparison", "scope_type": "multiple_minesites",
            "metric": "availability",
        }, {"rows": [{"Site": "Essakane", "Availability": .75}, {"Site": "Fekola", "Availability": .83}]})
        self.assertEqual(resolved.code, "comparison_compact_test")
        self.assertEqual(resolved.components[0], "comparison_table")

    def test_partial_comparison_uses_controlled_fallback(self):
        resolved = MachinePerformanceResponseTemplateResolver().resolve({
            "intent_type": "entity_comparison", "scope_type": "multiple_minesites",
            "metric": "availability",
        }, {"rows": [{"Site": "Essakane", "Availability": .75}]})
        self.assertEqual(resolved.code, "generic_analytical")
        self.assertTrue(resolved.warnings)

    def test_envelope_persists_template_and_adaptive_actions(self):
        envelope = self.planner.build_response_envelope(
            intent={"intent_type": "ranking", "scope_type": "multiple_equipment", "metric": "availability", "filters": {}},
            result={"rows": [{"SN": "A", "Availability": .5}]},
            answer_text="Ranked equipment.",
        )
        self.assertEqual(envelope["presentation"]["template_code"], "ranking")
        self.assertEqual(envelope["presentation"]["template_version"], "1.0")
        self.assertEqual(envelope["actions"][0]["code"], "open_equipment")

    @override_settings(ENABLE_ADAPTIVE_PERFORMANCE_RESPONSES="Disabled")
    def test_feature_flag_disables_adaptive_pipeline(self):
        self.assertFalse(adaptive_performance_responses_enabled())
        resolved = MachinePerformanceResponseTemplateResolver().resolve(
            {"intent_type": "single_kpi", "_adaptive_responses_enabled": False},
            {"rows": [{"Availability": .75}]},
        )
        self.assertEqual(resolved.code, "legacy_availability_response")


class AdaptiveFrontendContractTests(SimpleTestCase):
    def test_frontend_uses_per_message_template_registry(self):
        source = (settings.BASE_DIR / "reports" / "static" / "reports" / "ai.js").read_text(encoding="utf-8")
        self.assertIn("adaptiveResponseRenderers", source)
        self.assertIn("responseTemplateCode(payload)", source)
        self.assertIn("legacy_availability_response", source)


class PowerAutomateResilienceTests(SimpleTestCase):
    @patch("reports.power_automate.time.sleep")
    @patch("reports.power_automate.get_flow_url", return_value="https://flow.example.test")
    @patch("reports.power_automate.HTTP.post")
    def test_temporary_502_is_retried(self, post, _flow_url, _sleep):
        unavailable = Mock(status_code=502, text='{"error":{"code":"NoResponse"}}')
        success = Mock(status_code=200, text='{}')
        success.json.return_value = {"firstTableRows": [{"Downtime Hours": 12.5}]}
        post.side_effect = [unavailable, success]
        with patch("reports.system_configuration_service.integration_value", side_effect=lambda _a, key, default, **_kwargs: 1 if key == "retry_count" else default):
            result = execute_dax_via_flow({"query": "EVALUATE ROW()"})
        self.assertEqual(result["firstTableRows"][0]["Downtime Hours"], 12.5)
        self.assertEqual(post.call_count, 2)
