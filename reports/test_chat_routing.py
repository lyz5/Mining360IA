import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase, TestCase

from .chat_routing_service import classify_chat_question
from .intent_extractor_service import extract_intent
from .views import _execute_ai_ask


class ChatRoutingTests(TestCase):
    def _classify(self, question, entities=None):
        with patch(
            "reports.chat_routing_service.resolve_synonyms",
            return_value={"resolved_entities": entities or []},
        ):
            return classify_chat_question(question, section_code="performance")

    def test_greeting_does_not_query_semantic_model(self):
        result = self._classify("Bonjour")
        self.assertEqual(result["route"], "conversation")
        self.assertFalse(result["requires_semantic_model"])

    def test_kpi_definition_uses_knowledge_base(self):
        result = self._classify(
            "What is availability?",
            [{"entity_type": "KPI", "normalized_value": "availability"}],
        )
        self.assertEqual(result["route"], "knowledge_question")
        self.assertFalse(result["requires_semantic_model"])

    def test_kpi_value_with_filter_queries_semantic_model(self):
        result = self._classify(
            "Give me availability for Fekola YTD",
            [
                {"entity_type": "KPI", "normalized_value": "availability"},
                {"entity_type": "Filter Value", "normalized_value": "Fekola"},
            ],
        )
        self.assertEqual(result["route"], "semantic_query")
        self.assertTrue(result["requires_semantic_model"])

    def test_confirmation_queries_semantic_model(self):
        result = self._classify("Tu es sûr que c'est 91.97%?")
        self.assertEqual(result["reason"], "previous_result_confirmation")
        self.assertTrue(result["requires_semantic_model"])

    def test_root_cause_question_queries_semantic_model(self):
        result = self._classify(
            "Why did availability decrease?",
            [{"entity_type": "KPI", "normalized_value": "availability"}],
        )
        self.assertTrue(result["requires_semantic_model"])

    def test_value_question_without_filter_queries_semantic_model(self):
        result = self._classify(
            "Quelle est la disponibilité ?",
            [{"entity_type": "KPI", "normalized_value": "availability"}],
        )
        self.assertTrue(result["requires_semantic_model"])

    def test_prime_movers_open_command_is_navigation_and_keeps_machine(self):
        intent = extract_intent(
            "Ouvre le rapport Prime Movers Operational Status pour la machine DNR00153",
            "performance",
        )

        self.assertEqual(intent["intent_type"], "powerbi_navigation")
        self.assertEqual(intent["filters"]["serial_number"], "DNR00153")
        self.assertIn("Prime Movers Operational Status", intent["navigation"]["report_query"])


class ControlledSemanticRoutingTests(SimpleTestCase):
    @patch("reports.views.process_user_question")
    @patch("reports.ai_agent_execution_service.execute_agent_question")
    @patch("reports.agent_router_service.multi_agent_enabled", return_value=True)
    @patch("reports.views.PowerBIReport.objects.filter")
    def test_availability_bypasses_optional_multi_agent(
        self, report_filter, _multi_agent_enabled, execute_agent, process_question
    ):
        report_filter.return_value.exists.return_value = True
        process_question.return_value = {
            "ok": True,
            "answer": "The physical availability of machine DNR00153 is 86.10%.",
            "rows": [{"Physical Availability": 0.861}],
        }
        request = RequestFactory().post(
            "/ai/ask/",
            data=json.dumps({
                "question": "Availability for serial number DNR00153 in June 2026",
                "conversation": [],
            }),
            content_type="application/json",
        )
        request.user = SimpleNamespace(is_authenticated=True, is_staff=False, is_superuser=False)

        with (
            patch("reports.conversation_intent_service.handle_conversational_message", return_value=None),
            patch("reports.views.classify_chat_question", create=True),
            patch("reports.chat_routing_service.resolve_synonyms", return_value={"resolved_entities": []}),
        ):
            response = _execute_ai_ask(request)

        self.assertEqual(response.status_code, 200)
        execute_agent.assert_not_called()
        process_question.assert_called_once()
