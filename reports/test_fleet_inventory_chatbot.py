from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from openpyxl import load_workbook

from .chat_routing_service import classify_chat_question
from .conversation_follow_up_resolution_service import resolve_conversation_follow_up
from .fleet_excel_export_service import FleetExcelExportService
from .fleet_inventory_chat_service import (
    EquipmentSerialResolutionService,
    FleetModelSummaryService,
    FleetResultNormalizationService,
    FleetSemanticQueryService,
)
from .intent_extractor_service import extract_intent
from .models import AIConfigSection, AIConversation, AIConversationArtifact, AIConversationMessage, AIFilterMapping, PlatformUser, PowerBIReport
from .powerbi_interaction_orchestrator import process_user_question


FLEET_MAPPINGS = {
    "fleet_site": "Site",
    "fleet_equipment": "Equipment",
    "fleet_model": "Model",
    "fleet_family": "ParentProductGroup",
    "fleet_serial_number": "SN",
    "fleet_brand": "Brand",
    "fleet_equipment_id": "EquipID",
    "fleet_status": "Status",
    "fleet_smu": "SMU.SMU",
}


class FleetConfigurationMixin:
    def configure(self):
        section, _ = AIConfigSection.objects.get_or_create(code="performance", defaults={"name": "Performance", "is_active": True})
        for code, column in FLEET_MAPPINGS.items():
            AIFilterMapping.objects.update_or_create(
                section=section, filter_code=code,
                defaults={"filter_label": code, "powerbi_table_name": "EquipmentList_MiningProd", "powerbi_column_name": column, "data_type": "Text", "is_active": True},
            )
        PowerBIReport.objects.update_or_create(
            report_id="report-fpr",
            defaults={"section": section, "workspace_id": "workspace-fpr", "report_name": "FPR Global DB + RLS", "display_name": "Fleet Performance Report", "semantic_model_id": "dataset-fpr", "validation_status": "Validated", "is_active": True},
        )
        return section


class FleetIntentTests(TestCase):
    @patch("reports.chat_routing_service.resolve_synonyms", return_value={"resolved_entities": []})
    def test_fleet_routes_to_semantic_model(self, _resolve):
        self.assertTrue(classify_chat_question("C'est quoi la flotte de Fekola ?")["requires_semantic_model"])

    def test_site_fleet_is_not_availability(self):
        intent = extract_intent("C'est quoi la flotte de Fekola ?")
        self.assertEqual(intent["intent_type"], "get_site_fleet")
        self.assertEqual(intent["filters"]["minesite"], "Fekola")
        self.assertIsNone(intent["metric"])

    def test_english_and_model_intents(self):
        self.assertEqual(extract_intent("Give me the Fekola fleet.")["intent_type"], "get_site_fleet")
        intent = extract_intent("Give me the Fekola 777 fleet.")
        self.assertEqual(intent["intent_type"], "get_site_model_fleet")
        self.assertEqual(intent["filters"]["model"], "777")

    def test_serial_only_and_location_lookup(self):
        self.assertEqual(extract_intent("L7K00442")["intent_type"], "lookup_equipment_by_serial")
        intent = extract_intent("Where is APX01656?")
        self.assertEqual(intent["intent_type"], "lookup_equipment_by_serial")
        self.assertEqual(intent["filters"]["serial_number"], "apx01656")

    def test_availability_fleet_question_stays_performance(self):
        intent = extract_intent("What is the availability of the Fekola fleet?")
        self.assertNotIn(intent["intent_type"], {"get_site_fleet", "get_site_fleet_by_model", "get_site_model_fleet"})
        self.assertEqual(intent["metric"], "availability")


@override_settings(ENABLE_FLEET_INVENTORY_CHAT="Production", ENABLE_EQUIPMENT_SERIAL_LOOKUP="Production")
class FleetServiceTests(FleetConfigurationMixin, TestCase):
    def setUp(self):
        self.configure()
        self.user = get_user_model().objects.create_superuser("fleet-admin", "fleet@example.com", "secret")

    def test_dax_uses_only_equipment_master_fields_and_exact_text_filters(self):
        dax = FleetSemanticQueryService(self.user).build_details_dax(site="Fekola", model="777 WT")
        self.assertIn("'EquipmentList_MiningProd'[Site]", dax)
        self.assertIn("'EquipmentList_MiningProd'[SMU.SMU]", dax)
        self.assertIn('TREATAS({"Fekola"}', dax)
        self.assertIn('TREATAS({"777 WT"}', dax)
        self.assertNotIn("Avail", dax)

    def test_normalization_preserves_text_deduplicates_and_sorts_summary(self):
        raw = [
            {"Site": "Fekola", "Equipment": "BH005", "Model": "434", "Serial Number": "L7K00442", "Equipment ID": "3814"},
            {"Site": "Fekola", "Equipment": "BH005", "Model": "434", "Serial Number": "L7K00442", "Equipment ID": "3814"},
            {"Site": "Fekola", "Equipment": "EX007", "Model": "6020", "Serial Number": "DNR00119", "Equipment ID": "3815"},
            {"Site": "Fekola", "Equipment": "WT01", "Model": "777 WT", "Serial Number": "00A-1", "Equipment ID": "3816"},
        ]
        result = FleetResultNormalizationService.normalize(raw)
        summary = FleetModelSummaryService.summarize(result["rows"])
        self.assertEqual(result["distinct_equipment_count"], 3)
        self.assertEqual(result["duplicate_count"], 1)
        self.assertEqual(result["rows"][2]["model"], "777 WT")
        self.assertEqual(summary[0]["equipment_count"], 1)

    def test_unique_normalized_serial_preserves_source_value(self):
        rows = [{"serial_number": "APX 00253", "site": "Essakane", "equipment": "CM-807", "model": "785"}]
        resolution = EquipmentSerialResolutionService.resolve(rows, "APX00253", "serial")
        self.assertEqual(resolution["machine"]["serial_number"], "APX 00253")
        self.assertEqual(resolution["match_type"], "normalized_unique")


@override_settings(ENABLE_FLEET_EXCEL_EXPORT="Production")
class FleetExportTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("exporter")
        self.other = get_user_model().objects.create_user("other")
        conversation = AIConversation.objects.create(user=self.user, title="Fleet")
        message = AIConversationMessage.objects.create(conversation=conversation, role="assistant", content="Fleet", status="completed")
        self.artifact = AIConversationArtifact.objects.create(
            conversation=conversation, message=message, artifact_type="fleet_equipment_table",
            payload_json={"value": {"site": "Fekola", "model": None, "rows": [
                {"site": "Fekola", "equipment": "BH005", "model": "434", "serial_number": "L7K00442"},
                {"site": "Fekola", "equipment": "EX007", "model": "6020", "serial_number": "DNR00119"},
            ]}},
        )

    def test_excel_contains_exact_headers_and_text_values(self):
        export = FleetExcelExportService(self.user).build(self.artifact.id)
        workbook = load_workbook(BytesIO(export["content"].getvalue()))
        self.assertEqual(workbook.sheetnames, ["Fleet by Model", "Fleet Details", "Export Metadata"])
        sheet = workbook["Fleet Details"]
        self.assertEqual([cell.value for cell in sheet[1]], ["Site", "Equipment", "Model", "Serial Number"])
        self.assertEqual(sheet["C2"].number_format, "@")
        self.assertEqual(sheet["D2"].value, "L7K00442")
        self.assertEqual(sheet.freeze_panes, "A2")
        self.assertEqual(workbook["Export Metadata"]["B2"].value, "Mining360")
        self.assertEqual(export["row_count"], 2)

    def test_export_ownership_is_enforced(self):
        with self.assertRaises(Exception):
            FleetExcelExportService(self.other).build(self.artifact.id)


class FleetFollowUpTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("fleet-follow-up")
        self.conversation = AIConversation.objects.create(user=self.user, title="Fleet")
        assistant = AIConversationMessage.objects.create(
            conversation=self.conversation, role="assistant", content="Fleet", status="completed",
        )
        AIConversationArtifact.objects.create(
            conversation=self.conversation, message=assistant, artifact_type="response_snapshot",
            payload_json={
                "ok": True,
                "agent": {"code": "machine_performance"},
                "intent": {"section": "performance", "domain": "machine_performance", "intent_type": "get_site_fleet", "metric": None, "filters": {"minesite": "Fekola"}},
            },
        )

    def test_only_model_inherits_site(self):
        result = resolve_conversation_follow_up("Only the 789.", conversation_id=str(self.conversation.id), user=self.user)
        self.assertFalse(result["requires_clarification"])
        self.assertEqual(result["merged_intent"]["intent_type"], "get_site_model_fleet")
        self.assertEqual(result["merged_intent"]["filters"], {"minesite": "Fekola", "model": "789"})

    def test_download_reuses_fleet_context(self):
        result = resolve_conversation_follow_up("Download it.", conversation_id=str(self.conversation.id), user=self.user)
        self.assertFalse(result["requires_clarification"])
        self.assertEqual(result["merged_intent"]["intent_type"], "export_current_fleet")


@override_settings(ENABLE_FLEET_INVENTORY_CHAT="Production")
class FleetOrchestratorTests(FleetConfigurationMixin, TestCase):
    def setUp(self):
        self.configure()

    def site_user(self, site="Fekola"):
        user = get_user_model().objects.create_user(username=f"{site}-user")
        PlatformUser.objects.create(
            django_user=user, azure_ad_id=f"{site}-id", user_principal_name=f"{site}@example.com",
            display_name=f"{site} User", can_access_ai=True, can_access_reporting=True,
            business_performance_role="MineSite", business_performance_scope={"minesite": [site], "rls_role": site},
        )
        return user

    @patch("reports.powerbi_interaction_orchestrator.resolve_dataset_roles", return_value=["Fekola"])
    @patch("reports.powerbi_interaction_orchestrator.execute_fleet_inventory_intent")
    def test_returns_complete_fleet_contract_without_opening_report(self, execute_fleet, _roles):
        user = self.site_user()
        execute_fleet.return_value = {
            "answer": "La flotte de Fekola comprend 2 équipements répartis sur 1 modèles.",
            "intent": "get_site_fleet", "rows": [{"site": "Fekola", "equipment": "BH005", "model": "434", "serial_number": "L7K00442"}],
            "by_model": [{"model": "434", "equipment_count": 1, "share_of_fleet": 1}],
            "dax": "EVALUATE", "metric": "fleet_inventory", "measure": "", "site": "Fekola", "model": None,
            "distinct_equipment_count": 1, "duplicate_count": 0, "is_complete": True,
            "source": {"table": "EquipmentList_MiningProd"}, "powerbi_result": {"firstTableRows": []},
        }
        result = process_user_question("C'est quoi la flotte de Fekola ?", {"user": user}, {})
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["intent"]["intent_type"], "get_site_fleet")
        self.assertEqual(result["presentation"]["template_code"], "fleet_site_inventory")
        self.assertEqual(result["fleet_table"]["columns"], ["Site", "Equipment", "Model", "Serial Number"])
        self.assertFalse(result["intent"]["navigation"]["open_report"])

    @patch("reports.powerbi_interaction_orchestrator.execute_fleet_inventory_intent")
    def test_site_scope_blocks_other_site(self, execute_fleet):
        result = process_user_question("Quelle est la flotte de Essakane ?", {"user": self.site_user()}, {})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "minesite_scope_forbidden")
        execute_fleet.assert_not_called()
