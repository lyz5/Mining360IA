from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings

from .ai_agent_execution_service import execute_agent_question
from .ai_conversation_artifact_service import artifacts_from_response
from .ai_conversation_service import create_conversation
from .conversation_follow_up_resolution_service import (
    ConversationFollowUpResolutionService,
    get_last_successful_compatible_context,
)
from .models import (
    AIAgent,
    AIConfigSection,
    AIConversationArtifact,
    AIConversationMessage,
    KnowledgeSynonym,
)
from .temporal_expression_resolution_service import resolve_temporal_expression


User = get_user_model()


class TemporalExpressionResolutionTests(SimpleTestCase):
    def test_bilingual_month_is_canonical(self):
        for expression in ("pour le mois de Juin 2026", "for June 2026"):
            with self.subTest(expression=expression):
                result = resolve_temporal_expression(expression, reference_date=date(2026, 8, 8))
                self.assertEqual(result["value"], "2026-06")
                self.assertEqual(result["start_date"], "2026-06-01")
                self.assertEqual(result["end_date"], "2026-06-30")
                self.assertEqual(result["display_value_fr"], "Juin 2026")

    def test_relative_month_is_deterministic(self):
        result = resolve_temporal_expression("last month", reference_date=date(2026, 1, 15))
        self.assertEqual(result["value"], "2025-12")


@override_settings(
    ENABLE_CONVERSATIONAL_FOLLOW_UP_RESOLUTION="Production",
    FOLLOW_UP_MINIMUM_CONFIDENCE=85,
)
class ConversationFollowUpResolutionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="follow-owner")
        self.other = User.objects.create_user(username="follow-other")
        self.conversation = create_conversation(self.user)
        self.base_payload = {
            "ok": True,
            "agent": {"code": "machine_performance", "name": "Machine Performance"},
            "answer": "The physical availability of the 785 fleet at Essakane is 99.73%.",
            "intent": {
                "section": "performance",
                "domain": "machine_performance",
                "intent_type": "single_kpi",
                "metric": "availability",
                "primary_metric": "availability",
                "filters": {"minesite": "Essakane", "model": "785"},
            },
            "presentation": {"template_code": "single_kpi", "template_version": "1.0"},
        }
        self.base_message = AIConversationMessage.objects.create(
            conversation=self.conversation,
            role="assistant",
            status="completed",
            agent_code="machine_performance",
            content=self.base_payload["answer"],
        )
        artifacts_from_response(self.conversation, self.base_message, self.base_payload)
        self.service = ConversationFollowUpResolutionService()

    def resolve(self, text):
        return self.service.resolve(
            text,
            conversation_id=str(self.conversation.id),
            user=self.user,
        )

    def test_exact_month_only_follow_up(self):
        result = self.resolve("pour le mois de Juin 2026")
        self.assertTrue(result["is_follow_up"])
        self.assertEqual(result["message_type"], "follow_up_filter_update")
        self.assertEqual(result["language"], "fr")
        self.assertEqual(result["agent_code"], "machine_performance")
        intent = result["merged_intent"]
        self.assertEqual(intent["metric"], "availability")
        self.assertEqual(intent["filters"], {
            "minesite": "Essakane", "model": "785", "period": "2026-06",
        })
        self.assertEqual(result["operations"][0]["value"]["display_value_fr"], "Juin 2026")

    def test_model_and_metric_updates_override_inherited_values(self):
        model = self.resolve("and the 777?")
        self.assertEqual(model["merged_intent"]["filters"]["model"], "777")
        metric = self.resolve("and the MTBF?")
        self.assertEqual(metric["merged_intent"]["metric"], "mtbf")

    def test_complete_french_query_is_not_misclassified_as_follow_up(self):
        result = self.resolve(
            "pour le mois de juin 2026 la disponibilité des 789 de SNIM-guelb"
        )
        self.assertFalse(result["is_follow_up"])
        self.assertEqual(result["message_type"], "standalone_business_query")

    def test_hyphenated_minesite_is_resolved_in_follow_up_entities(self):
        section = AIConfigSection.objects.get(code="performance")
        KnowledgeSynonym.objects.create(
            section=section,
            canonical_term="SNIM-Guelb",
            synonym="SNIM-Guelb",
            normalized_value="SNIM-Guelb",
            entity_type="Mine Site",
            validation_status="Validated",
            is_active=True,
        )
        result = self.resolve("et SNIM-guelb ?")
        self.assertTrue(result["is_follow_up"])
        self.assertEqual(result["merged_intent"]["filters"]["minesite"], "SNIM-Guelb")

    @patch("reports.conversation_follow_up_resolution_service._configured_entities")
    def test_site_update_and_append(self, entities):
        entities.return_value = {"minesite": "Fekola"}
        changed = self.resolve("and Fekola?")
        self.assertEqual(changed["merged_intent"]["filters"]["minesite"], "Fekola")
        entities.return_value = {"minesite": "Siguiri"}
        appended = self.resolve("also Siguiri")
        self.assertEqual(appended["merged_intent"]["filters"]["minesite"], ["Essakane", "Siguiri"])

    def test_action_changes_template_intent_and_keeps_filters(self):
        result = self.resolve("show me the downtime drivers")
        self.assertEqual(result["merged_intent"]["intent_type"], "downtime_drivers")
        self.assertEqual(result["merged_intent"]["filters"]["model"], "785")

    def test_period_comparison_preserves_active_period(self):
        self.base_payload["intent"]["filters"]["period"] = "2026-06"
        self.base_message.artifacts.all().delete()
        artifacts_from_response(self.conversation, self.base_message, self.base_payload)
        result = self.resolve("compare with May 2026")
        self.assertEqual(result["merged_intent"]["intent_type"], "period_comparison")
        self.assertEqual(result["merged_intent"]["filters"]["period"], "2026-06")
        self.assertEqual(result["merged_intent"]["comparison"]["periods"], ["2026-06", "2026-05"])

    def test_clear_model_does_not_delete_history(self):
        artifact_count = AIConversationArtifact.objects.filter(conversation=self.conversation).count()
        result = self.resolve("show all models")
        self.assertNotIn("model", result["merged_intent"]["filters"])
        self.assertEqual(result["merged_intent"]["group_by"], ["model"])
        self.assertEqual(AIConversationArtifact.objects.filter(conversation=self.conversation).count(), artifact_count)

    def test_failed_latest_message_is_ignored(self):
        failed = AIConversationMessage.objects.create(
            conversation=self.conversation, role="assistant", status="failed", content="failed",
        )
        AIConversationArtifact.objects.create(
            conversation=self.conversation,
            message=failed,
            artifact_type="response_snapshot",
            payload_json={"ok": True, "intent": {"metric": "mtbf", "filters": {"minesite": "Wrong"}}},
        )
        context = get_last_successful_compatible_context(str(self.conversation.id), self.user)
        self.assertEqual(context["intent"]["metric"], "availability")

    def test_context_is_isolated_by_user_and_conversation(self):
        self.assertIsNone(get_last_successful_compatible_context(str(self.conversation.id), self.other))
        other_conversation = create_conversation(self.user)
        self.assertIsNone(get_last_successful_compatible_context(str(other_conversation.id), self.user))

    def test_no_previous_context_requests_natural_clarification(self):
        empty = create_conversation(self.user)
        result = self.service.resolve("for June 2026", conversation_id=str(empty.id), user=self.user)
        self.assertTrue(result["is_follow_up"])
        self.assertTrue(result["requires_clarification"])
        self.assertIn("Which KPI", result["clarification_question"])

    @patch("reports.ai_agent_execution_service.agent_allowed", return_value=True)
    @patch("reports.ai_agent_execution_service.process_user_question")
    def test_agent_router_receives_resolved_intent_before_execution(self, process, _allowed):
        AIAgent.objects.create(
            code="machine_performance", name="Machine Performance",
            agent_type="machine_performance", active=True, validation_status="Validated",
        )
        process.return_value = {
            "ok": True,
            "answer": "La disponibilité physique est de 80,00 %.",
            "intent": {**self.base_payload["intent"], "filters": {
                "minesite": "Essakane", "model": "785", "period": "2026-06",
            }},
            "rows": [{"Availability": .8}],
        }
        result = execute_agent_question(
            "pour le mois de Juin 2026",
            user=self.user,
            conversation_id=str(self.conversation.id),
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["routing"]["method"], "conversation_follow_up")
        self.assertEqual(result["routing"]["selected_agent"], "machine_performance")
        passed_context = process.call_args.kwargs["user_context"]
        self.assertEqual(passed_context["pre_extracted_intent"]["filters"]["period"], "2026-06")
