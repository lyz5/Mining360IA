from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from django.contrib.auth import get_user_model

from .business_performance_service import BusinessPerformanceService, QueryResult
from .intent_extractor_service import extract_intent
from .parts_sales_chat_service import execute_parts_sales_intent
from .powerbi_interaction_orchestrator import process_user_question
from .models import PlatformUser


class PartsSalesIntentTests(TestCase):
    def test_extracts_customer_parts_sales_in_english(self):
        intent = extract_intent("What are YTD Parts Sales for customer Fekola?")

        self.assertEqual(intent["section"], "parts_sales")
        self.assertEqual(intent["metric"], "parts_sales_ytd")
        self.assertEqual(intent["filters"]["customer"], "Fekola")
        self.assertEqual(intent["filters"]["period"], "year to date")

    def test_extracts_customer_parts_sales_in_french(self):
        intent = extract_intent("Quel est le chiffre d'affaires pièces YTD du client Fekola ?")

        self.assertEqual(intent["section"], "parts_sales")
        self.assertEqual(intent["filters"]["customer"], "Fekola")

    def test_extracts_minesite_breakdown(self):
        intent = extract_intent("Show YTD Parts Sales by MineSite")

        self.assertEqual(intent["group_by"], ["minesite"])

    def test_natural_sales_wording_routes_to_parts_ytd(self):
        intent = extract_intent("How much did we sell since the beginning of the year")

        self.assertEqual(intent["section"], "parts_sales")
        self.assertEqual(intent["metric"], "parts_sales_ytd")
        self.assertEqual(intent["filters"]["period"], "year to date")


class PartsSalesExecutionTests(TestCase):
    @patch("reports.parts_sales_chat_service.BusinessPerformanceService")
    def test_customer_uses_official_measure_and_matches_full_customer_name(self, service_class):
        service = service_class.return_value
        service.mapping.side_effect = lambda name: SimpleNamespace(
            display_name={"global_revenue_eur": "Revenue EUR", "customer": "Customer"}[name],
            object_name={"global_revenue_eur": "CA Facture EU", "customer": "Nom client"}[name],
        )
        service.sales_domain_query.return_value = QueryResult(
            rows=[
                {"Customer": "FEKOLA SA", "Revenue EUR": 22_820_989.73},
                {"Customer": "OTHER", "Revenue EUR": 10},
            ],
            dax="EVALUATE SUMMARIZECOLUMNS('GlobalCA'[Nom client], [CA Facture EU])",
        )

        result = execute_parts_sales_intent(
            {
                "filters": {"customer": "Fekola", "period": "year to date"},
                "group_by": [],
            },
            question_text="Quel est le CA pièces YTD du client Fekola ?",
        )

        self.assertEqual(result["value"], 22_820_989.73)
        self.assertEqual(result["measure"], "CA Facture EU")
        self.assertIn("22,8 M€", result["answer"])
        service.sales_domain_query.assert_called_once_with(
            "parts", {"year": str(date.today().year)}, dimension="customer", currency="EURO", limit=2000
        )

    @patch("reports.parts_sales_chat_service.BusinessPerformanceService")
    def test_minesite_breakdown_uses_analytical_territory(self, service_class):
        service = service_class.return_value
        service.mapping.side_effect = lambda name: SimpleNamespace(
            display_name={"global_revenue_eur": "Revenue EUR", "territory": "Analytical Territory"}[name],
            object_name={"global_revenue_eur": "CA Facture EU", "territory": "Territoire analytique"}[name],
        )
        service.sales_domain_query.return_value = QueryResult(
            rows=[{"Analytical Territory": "MALI", "Revenue EUR": 34_800_000}],
            dax="EVALUATE SUMMARIZECOLUMNS('GlobalCA'[Territoire analytique], [CA Facture EU])",
        )

        result = execute_parts_sales_intent(
            {"filters": {"period": "year to date"}, "group_by": ["minesite"]},
            question_text="Parts Sales YTD par MineSite",
        )

        self.assertEqual(result["dimension"], "territory")
        self.assertIn("MALI", result["answer"])

    def test_governed_query_uses_globalca_parts_direct_channels_and_official_measure(self):
        service = BusinessPerformanceService()
        with patch.object(service, "execute", return_value=QueryResult([], "")) as execute:
            service.sales_domain_query(
                "parts",
                {"year": str(date.today().year)},
                dimension="customer",
                currency="EURO",
            )

        dax = execute.call_args.args[0]
        self.assertIn("[CA Facture EU]", dax)
        self.assertIn("'GlobalCA'[Nom client]", dax)
        self.assertIn('TREATAS({"PARTS"}, \'GlobalCA\'[LOB])', dax)
        self.assertIn('TREATAS({"Onshore", "Offshore"}, \'GlobalCA\'[Canal de distribution])', dax)


class PartsSalesOrchestratorTests(TestCase):
    def _site_user(self):
        user = get_user_model().objects.create_user(username="fekola-site-user", email="fekola@neemba.com")
        PlatformUser.objects.create(
            django_user=user, azure_ad_id="fekola-site-user", user_principal_name="fekola@neemba.com",
            display_name="Fekola User", can_access_ai=True, can_access_reporting=True,
            business_performance_role="MineSite",
            business_performance_scope={"minesite": ["Fekola"], "rls_role": "Fekola"},
        )
        return user

    @patch("reports.powerbi_interaction_orchestrator.resolve_synonyms")
    @patch("reports.powerbi_interaction_orchestrator.execute_parts_sales_intent")
    def test_parts_question_bypasses_performance_synonyms_and_keeps_exact_result(
        self, execute_parts, resolve_synonyms
    ):
        user = get_user_model().objects.create_user(username="parts-chat-user")
        execute_parts.return_value = {
            "answer": "Le chiffre d'affaires Parts YTD de FEKOLA SA est de 22,8 M€.",
            "rows": [{"Nom client": "FEKOLA SA", "Revenue EUR": 22_820_989.73}],
            "dax": "EVALUATE ROW(\"Revenue EUR\", [CA Facture EU])",
            "metric": "parts_sales_ytd",
            "measure": "CA Facture EU",
            "dimension": "customer",
            "value": 22_820_989.73,
            "year": str(date.today().year),
            "cached": False,
        }

        result = process_user_question(
            "Quel est le chiffre d'affaires pièces YTD du client Fekola ?",
            {
                "user": user,
                "open_report": True,
                "dataset_name": "FPR Global DB + RLS",
            },
            {},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["answer"], execute_parts.return_value["answer"])
        self.assertEqual(result["intent"]["filters"]["customer"], "Fekola")
        self.assertNotIn("minesite", result["intent"]["filters"])
        self.assertEqual(result["measure"], "CA Facture EU")
        self.assertFalse(result["intent"]["navigation"]["open_report"])
        resolve_synonyms.assert_not_called()

    @patch("reports.powerbi_interaction_orchestrator.execute_parts_sales_intent")
    def test_minesite_user_chatbot_automatically_receives_site_scope(self, execute_parts):
        user = self._site_user()
        execute_parts.return_value = {
            "answer": "YTD Parts Sales for FEKOLA SA are 22.8 M€.", "rows": [],
            "dax": "EVALUATE ROW(\"Revenue EUR\", [CA Facture EU])",
            "metric": "parts_sales_ytd", "measure": "CA Facture EU", "dimension": "customer",
            "value": 22_800_000, "year": str(date.today().year), "cached": False,
        }

        result = process_user_question("How much did we sell since the beginning of the year", {"user": user}, {})

        self.assertTrue(result["ok"])
        self.assertEqual(execute_parts.call_args.args[0]["filters"]["minesite"], "Fekola")

    @patch("reports.powerbi_interaction_orchestrator.execute_parts_sales_intent")
    def test_minesite_user_cannot_query_another_site(self, execute_parts):
        user = self._site_user()

        result = process_user_question("Parts Sales YTD for MineSite Essakane", {"user": user}, {})

        self.assertFalse(result["ok"])
        self.assertEqual(result["status_code"], 403)
        self.assertEqual(result["error_code"], "minesite_scope_forbidden")
        execute_parts.assert_not_called()
