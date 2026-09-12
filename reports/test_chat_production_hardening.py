import json
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .ai_conversation_service import create_conversation
from .ai_conversation_message_service import create_assistant_placeholder, create_user_message
from .ai_conversation_execution_service import create_execution, transition
from .ai_feature_rollout import feature_enabled
from .chat_production_readiness_service import (
    ActionEligibilityService,
    ChatbotProductionReadinessService,
    ChatSuggestionService,
)
from .models import (
    AIChatInteractionEvent,
    AIChatSuggestion,
    AIConversationExecution,
    AIConversationMessage,
    FeaturePilotMembership,
    PlatformUser,
)


User = get_user_model()


@override_settings(
    ENABLE_CERTIFIED_CHAT_SUGGESTIONS="Production",
    ENABLE_OPERATION_LEVEL_READINESS="Production",
    ENABLE_ACTION_ELIGIBILITY="Production",
    ENABLE_CHATBOT_CAPABILITY_DISCOVERY="Production",
    ENABLE_GRACEFUL_ABSTENTION="Production",
    CHAT_CERTIFICATION_ENVIRONMENT="Development",
)
class ChatProductionHardeningTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("hardening-admin", "admin@example.com", "pass")
        PlatformUser.objects.create(
            azure_ad_id="hardening-admin",
            user_principal_name="admin@example.com",
            display_name="Hardening Admin",
            django_user=self.admin,
            can_access_ai=True,
            is_platform_admin=True,
        )
        self.user = User.objects.create_user("hardening-user", "user@example.com", "pass")
        PlatformUser.objects.create(
            azure_ad_id="hardening-user",
            user_principal_name="user@example.com",
            display_name="Hardening User",
            django_user=self.user,
            can_access_ai=True,
        )

    def test_only_certified_ready_starter_is_returned(self):
        payload = ChatSuggestionService().get_suggestions(self.admin, language="en")
        self.assertEqual([item["code"] for item in payload["suggestions"]], ["starter_capability_overview"])
        self.assertNotIn("legacy_analyze_repeated_failures", [item["code"] for item in payload["suggestions"]])

    def test_repeated_failures_is_explicitly_ineligible(self):
        suggestion = AIChatSuggestion.objects.get(suggestion_code="legacy_analyze_repeated_failures")
        _, decision = ChatSuggestionService().validate_execution(self.admin, suggestion.suggestion_code)
        self.assertFalse(decision.eligible)
        self.assertEqual(decision.reason_code, "SUGGESTION_FAILED")
        self.assertEqual(suggestion.certification_status, "FAILED")

    def test_suggestions_api_is_local_and_does_not_call_external_services(self):
        self.client.force_login(self.admin)
        with patch("reports.power_automate.execute_dax_via_flow") as powerbi, patch(
            "requests.sessions.Session.request"
        ) as provider:
            response = self.client.get(reverse("ai-chat-suggestions-api"), {"language": "en"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["suggestions"][0]["code"], "starter_capability_overview")
        powerbi.assert_not_called()
        provider.assert_not_called()

    def test_certified_suggestion_uses_normal_persistent_pipeline(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("ai-ask"),
            data=json.dumps({
                "question": "What can you do for me?",
                "client_message_id": "certified-help-client",
                "idempotency_key": "certified-help-idempotency",
                "source": "starter_suggestion",
                "suggestion_code": "starter_capability_overview",
                "guided_values": {},
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["persisted"])
        self.assertIn("capability_catalog", payload)
        messages = AIConversationMessage.objects.filter(conversation_id=payload["conversation_id"])
        self.assertEqual(messages.count(), 2)
        self.assertEqual(messages.get(role="user").metadata_json["suggestion_code"], "starter_capability_overview")
        self.assertTrue(AIChatInteractionEvent.objects.filter(event_type="suggestion_execution_checked", outcome="eligible").exists())
        execution = AIConversationExecution.objects.get(conversation_id=payload["conversation_id"])
        self.assertEqual(execution.status, "SUCCEEDED")
        self.assertEqual(
            [item["status"] for item in execution.status_history_json],
            ["QUEUED", "ROUTING", "CHECKING_ANSWERABILITY", "EXECUTING_DATA_SOURCE", "VALIDATING_GROUNDING", "SUCCEEDED"],
        )

    def test_ineligible_suggestion_returns_persisted_controlled_abstention(self):
        self.client.force_login(self.admin)
        with patch("reports.views._execute_ai_ask") as execute:
            response = self.client.post(
                reverse("ai-ask"),
                data=json.dumps({
                    "question": "Analyze repeated failures.",
                    "client_message_id": "repeat-client",
                    "idempotency_key": "repeat-idempotency",
                    "source": "starter_suggestion",
                    "suggestion_code": "legacy_analyze_repeated_failures",
                }),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ABSTAINED")
        self.assertEqual(response.json()["answerability"]["status"], "CAPABILITY_NOT_CONFIGURED")
        self.assertTrue(response.json()["persisted"])
        execute.assert_not_called()

    def test_manual_repeated_failures_is_stopped_before_powerbi(self):
        self.client.force_login(self.admin)
        with patch("reports.views._execute_ai_ask") as execute:
            response = self.client.post(
                reverse("ai-ask"),
                data=json.dumps({
                    "question": "Analyze repeated failures.",
                    "client_message_id": "manual-repeat-client",
                    "idempotency_key": "manual-repeat-idempotency",
                }),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["answerability"]["status"], "CAPABILITY_NOT_CONFIGURED")
        execute.assert_not_called()

    def test_idempotency_key_prevents_duplicate_messages(self):
        self.client.force_login(self.admin)
        body = {
            "question": "What can you do for me?",
            "client_message_id": "first-client-id",
            "idempotency_key": "same-logical-request",
            "source": "starter_suggestion",
            "suggestion_code": "starter_capability_overview",
        }
        first = self.client.post(reverse("ai-ask"), data=json.dumps(body), content_type="application/json").json()
        body["conversation_id"] = first["conversation_id"]
        body["client_message_id"] = "second-client-id"
        second = self.client.post(reverse("ai-ask"), data=json.dumps(body), content_type="application/json").json()
        self.assertTrue(second["idempotent_replay"])
        self.assertEqual(AIConversationMessage.objects.filter(conversation_id=first["conversation_id"]).count(), 2)

    def test_message_reuses_existing_empty_conversation_at_active_limit(self):
        empty = None
        for index in range(10):
            conversation = create_conversation(self.admin)
            if index < 9:
                create_user_message(
                    conversation,
                    content=f"Existing message {index}",
                    client_message_id=f"existing-{index}",
                )
            else:
                empty = conversation
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("ai-ask"),
            data=json.dumps({
                "question": "What can you do for me?",
                "client_message_id": "reuse-empty-client",
                "idempotency_key": "reuse-empty-key",
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["conversation_id"], str(empty.id))
        self.assertEqual(AIConversationMessage.objects.filter(conversation=empty).count(), 2)

    def test_active_limit_without_empty_conversation_is_not_retryable_source_failure(self):
        for index in range(10):
            conversation = create_conversation(self.user)
            create_user_message(
                conversation,
                content=f"Existing message {index}",
                client_message_id=f"full-{index}",
            )
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("ai-ask"),
            data=json.dumps({"question": "What can you do for me?"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error_code"], "CONVERSATION_LIMIT_REACHED")
        self.assertFalse(response.json()["retry"]["allowed"])

    def test_real_pilot_membership_allows_non_admin(self):
        with override_settings(TEST_PILOT_FEATURE="Pilot"):
            self.assertFalse(feature_enabled("TEST_PILOT_FEATURE", self.user))
            FeaturePilotMembership.objects.create(feature_flag="TEST_PILOT_FEATURE", user=self.user)
            self.assertTrue(feature_enabled("TEST_PILOT_FEATURE", self.user))

    def test_retry_action_is_only_available_for_transient_failure(self):
        service = ActionEligibilityService()
        allowed, _ = service.evaluate(
            self.admin,
            "retry",
            payload={"answerability": {"status": "TEMPORARILY_UNAVAILABLE"}},
        )
        denied, reason = service.evaluate(
            self.admin,
            "retry",
            payload={"answerability": {"status": "ENTITY_NOT_FOUND"}},
        )
        self.assertTrue(allowed)
        self.assertFalse(denied)
        self.assertEqual(reason, "FAILURE_NOT_RETRYABLE")

    def test_powerbi_action_is_hidden_without_a_valid_report_target(self):
        allowed, reason = ActionEligibilityService().evaluate(
            self.admin,
            "open_powerbi",
            payload={"navigation": {}},
        )
        self.assertFalse(allowed)
        self.assertEqual(reason, "REPORT_NAVIGATION_UNAVAILABLE")

    @override_settings(
        ENABLE_CHAT_DEAD_SUGGESTION_AUTO_HIDE="Production",
        CHAT_DEAD_SUGGESTION_MINIMUM_SAMPLES=3,
        CHAT_SUGGESTION_MINIMUM_SUCCESS_RATE=0.95,
    )
    def test_dead_suggestion_is_automatically_invalidated(self):
        suggestion = AIChatSuggestion.objects.get(suggestion_code="starter_capability_overview")
        for _ in range(3):
            AIChatInteractionEvent.objects.create(
                event_type="suggestion_execution_completed",
                suggestion=suggestion,
                user=self.admin,
                outcome="RETRYABLE_FAILED",
            )
        hidden = ChatbotProductionReadinessService().auto_hide_dead_suggestions()
        suggestion.refresh_from_db()
        self.assertEqual(hidden, ["starter_capability_overview"])
        self.assertEqual(suggestion.certification_status, "INVALIDATED")

    def test_readiness_dashboard_is_admin_only(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("ai-chat-production-readiness-api")).status_code, 403)
        self.assertIn(self.client.get(reverse("ai-chat-production-readiness")).status_code, {302, 403})
        self.client.force_login(self.admin)
        response = self.client.get(reverse("ai-chat-production-readiness-api"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("suggestions", response.json())
        page = self.client.get(reverse("ai-chat-production-readiness"))
        self.assertContains(page, "Chatbot Production Readiness")
        self.assertContains(page, "legacy_analyze_repeated_failures")

    def test_running_execution_can_be_cancelled_without_removing_user_message(self):
        conversation = create_conversation(self.admin)
        user_message, _ = create_user_message(
            conversation,
            content="Long running analysis",
            client_message_id="cancel-client",
            idempotency_key="cancel-idempotency",
        )
        assistant = create_assistant_placeholder(user_message)
        execution = create_execution(
            conversation=conversation,
            user_message=user_message,
            assistant_message=assistant,
            payload={"client_execution_id": "cancel-execution"},
        )
        transition(execution, "EXECUTING_DATA_SOURCE")
        self.client.force_login(self.admin)
        response = self.client.post(reverse("ai-chat-execution-cancel-api", args=["cancel-execution"]), data="{}", content_type="application/json")
        self.assertEqual(response.status_code, 200)
        execution.refresh_from_db()
        assistant.refresh_from_db()
        self.assertEqual(execution.status, "CANCELLED")
        self.assertEqual(assistant.status, "cancelled")
        self.assertTrue(AIConversationMessage.objects.filter(pk=user_message.pk).exists())

    def test_static_uncontrolled_starter_prompts_are_removed(self):
        javascript = (Path(settings.BASE_DIR) / "reports" / "static" / "reports" / "ai.js").read_text(encoding="utf-8")
        self.assertNotIn('data-suggested-prompt="Analyze repeated failures.', javascript)
        self.assertIn("/api/ai/chat/suggestions/", javascript)
        self.assertIn("submitCertifiedSuggestion", javascript)
        self.assertNotIn("error.message ||", javascript)
        self.assertNotIn("Response generation failed", javascript)
