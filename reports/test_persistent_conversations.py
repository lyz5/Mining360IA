import json
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.http import JsonResponse
from django.test import TestCase, override_settings
from django.urls import reverse

from .ai_conversation_artifact_service import artifacts_from_response
from .ai_conversation_context_service import merge_conversation_context
from .ai_conversation_message_service import (
    create_assistant_placeholder,
    create_user_message,
    finalize_assistant_message,
)
from .ai_conversation_service import ConversationLimitReached, create_conversation, rename_conversation
from .conversation_intent_service import classify_conversation_intent
from .models import (
    AIConfigSection,
    AIConversation,
    AIConversationArtifact,
    AIConversationMessage,
    KnowledgeSynonym,
    PlatformUser,
)
from .powerbi_interaction_orchestrator import _natural_availability_answer
from .powerbi_interaction_service import is_follow_up_question, merge_conversation_intent
from .synonym_resolution_service import resolve_synonyms


User = get_user_model()


@override_settings(
    ENABLE_PERSISTENT_CONVERSATIONS=True,
    ENABLE_CONVERSATION_RENAME=True,
    ENABLE_CONVERSATION_ARTIFACTS=True,
    MAX_ACTIVE_CONVERSATIONS_PER_USER=10,
)
class PersistentConversationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="chat-owner", password="pass")
        self.other = User.objects.create_user(username="other-user", password="pass")
        PlatformUser.objects.create(
            azure_ad_id="chat-owner-id",
            user_principal_name="chat-owner@example.com",
            display_name="Chat Owner",
            django_user=self.user,
            can_access_ai=True,
        )
        self.client.force_login(self.user)

    def test_create_conversation_and_enforce_active_limit(self):
        for _ in range(10):
            create_conversation(self.user)
        with self.assertRaises(ConversationLimitReached):
            create_conversation(self.user)

    def test_conversation_api_is_scoped_to_owner(self):
        foreign = create_conversation(self.other)
        response = self.client.get(reverse("ai-conversation-api", args=[foreign.id]))
        self.assertEqual(response.status_code, 404)

    def test_conversation_workspace_routes_render(self):
        conversation = create_conversation(self.user)
        for route in (
            reverse("ai-home"),
            reverse("ai-new"),
            reverse("ai-conversation-page", args=[conversation.id]),
        ):
            response = self.client.get(route)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'id="ai-message-scroll"')

    def test_manual_title_is_preserved(self):
        conversation = create_conversation(self.user)
        rename_conversation(conversation, "  Essakane 785 Availability  ")
        conversation.refresh_from_db()
        self.assertEqual(conversation.title, "Essakane 785 Availability")
        self.assertTrue(conversation.title_is_manual)

    def test_soft_delete_removes_conversation_from_active_list(self):
        conversation = create_conversation(self.user)
        response = self.client.delete(reverse("ai-conversation-api", args=[conversation.id]))
        self.assertEqual(response.status_code, 200)
        conversation.refresh_from_db()
        self.assertEqual(conversation.status, "deleted")
        listing = self.client.get(reverse("ai-conversations-api")).json()
        self.assertEqual(listing["count"], 0)

    def test_message_idempotence(self):
        conversation = create_conversation(self.user)
        first, created = create_user_message(
            conversation,
            content="What is PA?",
            client_message_id="browser-message-1",
        )
        second, created_again = create_user_message(
            conversation,
            content="What is PA?",
            client_message_id="browser-message-1",
        )
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first.id, second.id)

    def test_artifact_and_context_are_persistent(self):
        conversation = create_conversation(self.user)
        message = AIConversationMessage.objects.create(
            conversation=conversation,
            role="assistant",
            status="completed",
            content="Availability is 82.82%.",
        )
        artifacts_from_response(
            conversation,
            message,
            {"ok": True, "availability_diagnostics": {"availability": 82.82, "drivers": []}},
        )
        merge_conversation_context(
            conversation,
            performance_context={"minesite": "Essakane", "model": "785"},
            active_analysis={"active_view": "root_cause_explorer", "downtime_driver": "Power Train"},
        )
        self.assertTrue(AIConversationArtifact.objects.filter(conversation=conversation, artifact_type="response_snapshot").exists())
        conversation.refresh_from_db()
        self.assertEqual(conversation.performance_context_json["model"], "785")
        self.assertEqual(conversation.active_analysis_json["active_view"], "root_cause_explorer")

    @patch("reports.views._execute_ai_ask")
    def test_ai_response_is_saved_before_return_and_replayed_idempotently(self, execute):
        execute.return_value = JsonResponse({
            "ok": True,
            "chat_message": "PA is 82.82%.",
            "intent": {"metric": "availability", "filters": {"minesite": "Essakane", "model": "785"}},
            "availability_diagnostics": {"availability": 82.82, "drivers": []},
        })
        conversation = create_conversation(self.user)
        client_message_id = str(uuid.uuid4())
        body = {
            "question": "What is the PA of Essakane 785?",
            "conversation_id": str(conversation.id),
            "client_message_id": client_message_id,
        }
        response = self.client.post(reverse("ai-ask"), data=json.dumps(body), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["persisted"])
        self.assertEqual(AIConversationMessage.objects.filter(conversation=conversation).count(), 2)
        self.assertTrue(AIConversationArtifact.objects.filter(conversation=conversation, artifact_type="response_snapshot").exists())

        replay = self.client.post(reverse("ai-ask"), data=json.dumps(body), content_type="application/json")
        self.assertEqual(replay.status_code, 200)
        self.assertTrue(replay.json()["idempotent_replay"])
        self.assertEqual(AIConversationMessage.objects.filter(conversation=conversation).count(), 2)
        self.assertEqual(execute.call_count, 1)

    def test_message_history_reopens_with_artifacts(self):
        conversation = create_conversation(self.user)
        message = AIConversationMessage.objects.create(
            conversation=conversation,
            role="assistant",
            status="completed",
            content="Saved result",
        )
        AIConversationArtifact.objects.create(
            conversation=conversation,
            message=message,
            artifact_type="kpi_result",
            payload_json={"value": 82.82},
        )
        response = self.client.get(reverse("ai-conversation-messages-api", args=[conversation.id]))
        self.assertEqual(response.status_code, 200)
        result = response.json()["results"][0]
        self.assertEqual(result["content"], "Saved result")
        self.assertEqual(result["artifacts"][0]["payload"]["value"], 82.82)

    def test_greeting_is_persisted_without_agent_or_clarification(self):
        conversation = create_conversation(self.user)
        response = self.client.post(
            reverse("ai-ask"),
            data=json.dumps({
                "question": "Bonjour",
                "conversation_id": str(conversation.id),
                "client_message_id": "bonjour-1",
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["chat_message"], "Bonjour ! Comment puis-je vous aider aujourd'hui ?")
        assistant = conversation.messages.filter(role="assistant").get()
        self.assertEqual(assistant.agent_code, "")
        self.assertFalse(assistant.metadata_json["response_payload"]["requires_clarification"])

    def test_availability_topic_setting_is_conversational(self):
        classification = classify_conversation_intent("I have some questions about availability")
        self.assertTrue(classification["is_conversational"])
        self.assertEqual(classification["intent"], "small_talk")
        self.assertEqual(classification["topic"], "availability")

    def test_each_analytical_message_keeps_its_own_immutable_snapshot(self):
        conversation = create_conversation(self.user)
        snapshots = []
        for site, value in (("Fekola", 0.8362), ("Essakane", 0.7542)):
            user_message, _ = create_user_message(
                conversation,
                content=f"Give me the availability of {site} May 2026",
                client_message_id=f"question-{site}",
            )
            assistant = create_assistant_placeholder(user_message)
            finalize_assistant_message(assistant, {
                "ok": True,
                "chat_message": f"The physical availability at {site} is {value * 100:.2f}% for May 2026.",
                "intent": {"metric": "availability", "filters": {"minesite": site, "period": "2026-05"}},
                "rows": [{"Availability": value}],
                "availability_diagnostics": {"total_downtime_hours": 10, "drivers": []},
                "agent": {"code": "machine_performance", "name": "Machine Performance"},
            })
            snapshots.append(
                AIConversationArtifact.objects.get(message=assistant, artifact_type="response_snapshot")
            )
        self.assertNotEqual(snapshots[0].message_id, snapshots[1].message_id)
        self.assertEqual(snapshots[0].payload_json["intent"]["filters"]["minesite"], "Fekola")
        self.assertEqual(snapshots[1].payload_json["intent"]["filters"]["minesite"], "Essakane")
        snapshots[0].refresh_from_db()
        self.assertEqual(snapshots[0].payload_json["intent"]["filters"]["minesite"], "Fekola")

    def test_refresh_creates_new_artifact_version_without_mutating_original(self):
        conversation = create_conversation(self.user)
        original_user, _ = create_user_message(
            conversation,
            content="Give me Fekola availability",
            client_message_id="original",
        )
        original_assistant = create_assistant_placeholder(original_user)
        finalize_assistant_message(original_assistant, {
            "ok": True,
            "chat_message": "83.62%",
            "intent": {"metric": "availability", "filters": {"minesite": "Fekola"}},
        })
        original = AIConversationArtifact.objects.get(
            message=original_assistant,
            artifact_type="response_snapshot",
        )
        refreshed_user, _ = create_user_message(
            conversation,
            content="Give me Fekola availability",
            client_message_id="refresh",
            metadata={"refresh_of_artifact_id": str(original.id)},
        )
        refreshed_assistant = create_assistant_placeholder(refreshed_user)
        finalize_assistant_message(refreshed_assistant, {
            "ok": True,
            "chat_message": "84.00%",
            "intent": {"metric": "availability", "filters": {"minesite": "Fekola"}},
        })
        refreshed = AIConversationArtifact.objects.get(
            message=refreshed_assistant,
            artifact_type="response_snapshot",
        )
        self.assertEqual(original.artifact_version, 1)
        self.assertEqual(refreshed.artifact_version, 2)
        self.assertEqual(refreshed.supersedes_artifact_id, original.id)
        self.assertIsNotNone(refreshed.refreshed_at)
        original.refresh_from_db()
        self.assertEqual(original.payload_json["chat_message"], "83.62%")

    def test_essakne_resolves_to_validated_essakane(self):
        section = AIConfigSection.objects.get(code="performance")
        KnowledgeSynonym.objects.update_or_create(
            section=section,
            entity_type="Mine Site",
            language="en",
            normalized_synonym_key="essakane",
            defaults={
                "canonical_term": "Essakane",
                "synonym": "Essakane",
                "normalized_value": "Essakane",
                "match_type": "Exact",
                "confidence": 100,
                "resolution_priority": 100,
                "validation_status": "Validated",
                "is_active": True,
            },
        )
        resolution = resolve_synonyms(
            "Give me the availability of Essakne May 2026",
            section_code="performance",
            mode="Production",
        )
        site = next(
            item for item in resolution["resolved_entities"]
            if item["normalized_value"] == "Essakane"
        )
        self.assertEqual(site["original_value"], "Essakne")
        self.assertGreaterEqual(site["confidence"], 85)

    def test_natural_answer_includes_normalized_site_and_month_name(self):
        answer = _natural_availability_answer(
            {"filters": {"minesite": "Essakane", "period": "2026-05"}},
            0.7542,
            "Give me availability",
        )
        self.assertEqual(
            answer,
            "The physical availability at Essakane is 75.42% for May 2026.",
        )

    def test_follow_up_reuses_metric_and_period_but_changes_site(self):
        self.assertTrue(is_follow_up_question("What about Siguiri?"))
        merged = merge_conversation_intent(
            {
                "section": "performance",
                "intent_type": "single_kpi",
                "metric": None,
                "filters": {"minesite": "Siguiri"},
            },
            {
                "section": "performance",
                "intent_type": "single_kpi",
                "metric": "availability",
                "filters": {"minesite": "Essakane", "period": "2026-05"},
            },
            inherit_previous=True,
        )
        self.assertEqual(merged["metric"], "availability")
        self.assertEqual(merged["filters"], {"minesite": "Siguiri", "period": "2026-05"})

    @patch("reports.agent_router_service.multi_agent_enabled", return_value=True)
    @patch("reports.ai_agent_execution_service.execute_agent_question")
    def test_required_four_turn_scenario_is_append_only(self, execute_agent, _multi_agent):
        def result(question, **_kwargs):
            site = "Fekola" if "Fekola" in question else "Essakane"
            value = 0.8362 if site == "Fekola" else 0.7542
            return {
                "ok": True,
                "chat_message": f"The physical availability at {site} is {value * 100:.2f}% for May 2026.",
                "agent": {"code": "machine_performance", "name": "Machine Performance"},
                "intent": {"metric": "availability", "filters": {"minesite": site, "period": "2026-05"}},
                "rows": [{"Availability": value}],
                "availability_diagnostics": {"total_downtime_hours": 100, "drivers": []},
                "navigation": {},
                "requires_clarification": False,
            }

        execute_agent.side_effect = result
        conversation = create_conversation(self.user)
        questions = (
            "Bonjour",
            "I have some questions about availability",
            "Give me the availability of Fekola May 2026",
            "Give me the availability of Essakane May 2026",
        )
        for index, question in enumerate(questions):
            response = self.client.post(
                reverse("ai-ask"),
                data=json.dumps({
                    "question": question,
                    "conversation_id": str(conversation.id),
                    "client_message_id": f"scenario-{index}",
                }),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200)

        history = self.client.get(
            reverse("ai-conversation-messages-api", args=[conversation.id])
        ).json()["results"]
        self.assertEqual(len(history), 8)
        self.assertEqual([item["role"] for item in history], ["user", "assistant"] * 4)
        analytical = [item for item in history if item["message_type"] == "analytical_result"]
        self.assertEqual(len(analytical), 2)
        sites = [
            next(
                artifact["payload"]["intent"]["filters"]["minesite"]
                for artifact in item["artifacts"]
                if artifact["artifact_type"] == "response_snapshot"
            )
            for item in analytical
        ]
        self.assertEqual(sites, ["Fekola", "Essakane"])
        self.assertEqual(execute_agent.call_count, 2)
