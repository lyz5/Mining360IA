from unittest.mock import patch

from django.test import SimpleTestCase

from .chat_routing_service import classify_chat_question


class ChatRoutingTests(SimpleTestCase):
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
