from io import BytesIO

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from openpyxl import load_workbook

from .dax_generator_service import generate_fleet_performance_dax
from .fleet_performance_intelligence_service import (
    coverage_from_row,
    deterministic_performance_answer,
    enrich_fleet_performance_intent,
    normalize_result_metrics,
)
from .fleet_performance_excel_export_service import FleetPerformanceExcelExportService
from .intent_extractor_service import extract_intent
from .machine_performance_intent_service import detect_machine_performance_intent
from .machine_performance_response_service import (
    complete_fleet_performance_enabled,
    fleet_performance_operation_enabled,
)
from .powerbi_interaction_orchestrator import process_user_question
from .models import (
    AIConversation,
    AIConversationArtifact,
    AIConversationMessage,
    AIMetricMapping,
    KnowledgeKPIDictionary,
)


class FleetPerformanceIntentTests(TestCase):
    def test_general_performance_resolves_the_six_metric_bundle_without_provider(self):
        intent = extract_intent("Donne-moi la performance de Fekola YTD.", "performance")

        self.assertEqual(intent["capability"], "fleet_performance")
        self.assertEqual(intent["intent_type"], "fleet_performance_overview")
        self.assertEqual(intent["metric_bundle"], "fleet_performance_core")
        self.assertEqual(len(intent["metrics"]), 6)
        self.assertEqual(intent["filters"]["period"], "year to date")

    def test_reliability_question_resolves_only_mtbs_mtbf_mttr(self):
        intent = extract_intent("Give me MTBS, MTBF and MTTR for Essakane 785.", "performance")

        self.assertEqual(intent["intent_type"], "reliability_overview")
        self.assertEqual(intent["metric_bundle"], "reliability_core")
        self.assertEqual(intent["metrics"], ["mtbs", "mtbf", "mttr"])

    def test_planned_unplanned_is_not_an_availability_question(self):
        intent = extract_intent(
            "What percentage of Essakane 785 downtime is planned versus unplanned?",
            "performance",
        )

        self.assertEqual(intent["intent_type"], "planned_unplanned_analysis")
        self.assertEqual(intent["metric_bundle"], "downtime_mix")
        self.assertNotIn("availability", intent["metrics"])

    def test_inventory_and_performance_remain_distinct(self):
        self.assertEqual(detect_machine_performance_intent("Give me the Fekola fleet."), "get_site_fleet")
        self.assertEqual(
            detect_machine_performance_intent("Give me the Fekola fleet performance YTD."),
            "performance_overview",
        )
        performance = enrich_fleet_performance_intent(
            {"intent_type": "performance_overview", "filters": {}},
            "Give me the Fekola fleet performance.",
        )
        self.assertEqual(performance["intent_type"], "fleet_performance_overview")

    def test_serial_performance_does_not_route_to_master_data_lookup(self):
        intent = extract_intent("Give me the performance of serial KDP00232.", "performance")

        self.assertEqual(intent["intent_type"], "serial_performance")
        self.assertEqual(intent["capability"], "fleet_performance")
        self.assertEqual(intent["filters"]["serial_number"], "KDP00232")
        self.assertEqual(intent["metric_bundle"], "fleet_performance_core")


class FleetPerformanceConfigurationTests(TestCase):
    def test_exact_semantic_measures_are_configured(self):
        expected = {
            "availability": "[Availability New]",
            "mtbs": "[MTBS Per Equip]",
            "mtbf": "[MTBF Per Equip]",
            "mttr": "[MTTR Per Equip]",
            "planned_downtime_percentage": "[% PlannedHours DT]",
            "unplanned_downtime_percentage": "[% UnplannedHours DT]",
        }
        configured = dict(
            AIMetricMapping.objects.filter(
                section__code="performance", metric_code__in=expected,
            ).values_list("metric_code", "powerbi_measure_name")
        )
        self.assertEqual(configured, expected)
        self.assertEqual(
            KnowledgeKPIDictionary.objects.filter(
                section__code="performance", kpi_code__in=expected, is_active=True,
            ).count(),
            6,
        )

    def test_core_overview_uses_one_query_and_never_averages_ratios(self):
        dax = generate_fleet_performance_dax({
            "section": "performance",
            "intent_type": "fleet_performance_overview",
            "metric_bundle": "fleet_performance_core",
            "filters": {"minesite": "Fekola", "period": "year to date"},
        })["dax"]

        self.assertEqual(dax.count("EVALUATE"), 1)
        for measure in (
            "[Availability New]", "[MTBS Per Equip]", "[MTBF Per Equip]",
            "[MTTR Per Equip]", "[% PlannedHours DT]", "[% UnplannedHours DT]",
        ):
            self.assertIn(measure, dax)
        self.assertNotIn("AVERAGEX", dax.upper())
        self.assertIn("MIN(TODAY(), CALCULATE(MAX('Date'[Date])", dax)
        self.assertIn('TREATAS({"Fekola"}', dax)

    def test_equipment_ranking_keeps_mandatory_identity_columns(self):
        dax = generate_fleet_performance_dax({
            "section": "performance",
            "intent_type": "ranking",
            "query_intent_type": "ranking",
            "metric": "availability",
            "metrics": ["availability"],
            "filters": {"minesite": "Fekola", "period": "year to date"},
            "comparison": {"dimension": "equipment", "direction": "asc", "top_n": 10},
        })["dax"]

        for column in ("[Site]", "[Equipment]", "[Model]", "[SN]"):
            self.assertIn(column, dax)
        self.assertIn("TOPN(10", dax)
        self.assertIn("[Physical Availability], ASC", dax)


class FleetPerformancePresentationTests(SimpleTestCase):
    def test_percentage_values_are_scaled_only_for_display(self):
        metrics = normalize_result_metrics({
            "[Availability New]": 0.841,
            "[% PlannedHours DT]": 0.35,
            "[% UnplannedHours DT]": 0.65,
            "[MTBF Per Equip]": 14.180555,
        })
        indexed = {item["code"]: item for item in metrics}

        self.assertEqual(indexed["availability"]["raw_value"], 0.841)
        self.assertEqual(indexed["availability"]["formatted_value"], "84.10%")
        self.assertEqual(indexed["planned_downtime_percentage"]["formatted_value"], "35.00%")
        self.assertEqual(indexed["mtbf"]["formatted_value"], "14.18 h")

    def test_coverage_does_not_turn_missing_data_into_zero(self):
        coverage = coverage_from_row({"[Fleet Equipment]": 217, "[Equipment With Data]": 186})
        self.assertEqual(coverage["equipment_without_data"], 31)
        self.assertAlmostEqual(coverage["coverage_percentage"], 186 / 217)
        self.assertIsNone(coverage_from_row({})["coverage_percentage"])

    def test_provider_independent_answer_contains_all_returned_metrics(self):
        answer = deterministic_performance_answer(
            {"filters": {"minesite": "Fekola", "period": "year to date"}},
            [{"[Availability New]": 0.8914, "[MTBF Per Equip]": 40.435}],
            "en",
        )
        self.assertIn("Physical Availability: 89.14%", answer)
        self.assertIn("MTBF: 40.44 h", answer)

    def test_comparison_answer_does_not_present_the_first_row_as_the_whole_result(self):
        answer = deterministic_performance_answer(
            {"intent_type": "entity_comparison", "filters": {"period": "year to date"}},
            [{"MineSite": "Fekola", "[MTBF]": 40.4}, {"MineSite": "Essakane", "[MTBF]": 14.0}],
            "en",
        )
        self.assertEqual(answer, "The comparison of 2 entities (year to date) is available below.")

    @override_settings(ENABLE_COMPLETE_FLEET_PERFORMANCE_CHAT="Admin Only")
    def test_admin_only_feature_flag(self):
        User = get_user_model()
        self.assertTrue(complete_fleet_performance_enabled(User(is_staff=True)))
        self.assertFalse(complete_fleet_performance_enabled(User(is_staff=False)))

    @override_settings(ENABLE_FLEET_PERFORMANCE_TRENDS="Disabled")
    def test_operation_specific_feature_flag(self):
        User = get_user_model()
        self.assertFalse(fleet_performance_operation_enabled("trend_analysis", User(is_staff=True)))
        self.assertTrue(fleet_performance_operation_enabled("single_kpi", User(is_staff=False)))


@override_settings(
    ENABLE_COMPLETE_FLEET_PERFORMANCE_CHAT="Production",
    ENABLE_FLEET_PERFORMANCE_EXPORT="Production",
)
class FleetPerformanceExportTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("performance-exporter")
        self.other = get_user_model().objects.create_user("performance-other")
        conversation = AIConversation.objects.create(user=self.user, title="Performance")
        message = AIConversationMessage.objects.create(
            conversation=conversation,
            role="assistant",
            content="Performance",
            status="completed",
        )
        self.artifact = AIConversationArtifact.objects.create(
            conversation=conversation,
            message=message,
            artifact_type="fleet_performance_analysis",
            payload_json={"value": {
                "intent_type": "ranking",
                "metric_bundle": "availability_reliability",
                "context": {"minesite": "Fekola"},
                "metrics": [{
                    "code": "availability",
                    "label": "Physical Availability",
                    "raw_value": 0.8618,
                    "formatted_value": "86.18%",
                    "unit": "percentage",
                }],
                "rows": [{
                    "EquipmentList_MiningProd[Site]": "Fekola",
                    "EquipmentList_MiningProd[Equipment]": "HT005",
                    "EquipmentList_MiningProd[Model]": "777",
                    "EquipmentList_MiningProd[SN]": "KDP00232",
                    "[Physical Availability]": 0.8618,
                }],
                "source": {"semantic_model_name": "FPR Global DB + RLS"},
            }},
        )

    def test_export_uses_saved_rows_and_mining360_metadata(self):
        export = FleetPerformanceExcelExportService(self.user).build(self.artifact.id)
        workbook = load_workbook(BytesIO(export["content"].getvalue()))
        sheet = workbook["Performance Results"]

        self.assertEqual(
            [cell.value for cell in sheet[1]],
            ["Site", "Equipment", "Model", "Serial Number", "Physical Availability"],
        )
        self.assertEqual(sheet["C2"].number_format, "@")
        self.assertEqual(sheet["D2"].number_format, "@")
        self.assertEqual(sheet["D2"].value, "KDP00232")
        self.assertEqual(workbook["Export Metadata"]["B2"].value, "Mining360")

    def test_export_ownership_is_enforced(self):
        with self.assertRaises(Exception):
            FleetPerformanceExcelExportService(self.other).build(self.artifact.id)

    def test_download_follow_up_reuses_saved_artifact_without_semantic_query(self):
        previous_intent = {
            "section": "performance",
            "intent_type": "fleet_performance_overview",
            "capability": "fleet_performance",
            "metric_bundle": "fleet_performance_core",
            "metrics": ["availability", "mtbf"],
            "filters": {"minesite": "Fekola", "period": "year to date"},
        }
        result = process_user_question(
            "Download it.",
            {"user": self.user},
            {"conversation_id": str(self.artifact.conversation_id), "validated_intent": previous_intent},
        )

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["intent"]["intent_type"], "export_current_result")
        self.assertEqual(result["powerbi_result"]["saved_artifact_id"], str(self.artifact.id))
        self.assertEqual(result["dax"], "")
