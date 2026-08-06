from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from .agent_context_service import update_agent_context
from .agent_router_service import route_question
from .ai_agent_bootstrap_service import bootstrap_ai_agents
from .models import (
    AIAgent,
    AIAgentCapability,
    AIAgentExecutionLog,
    AIAgentRoutingRule,
    AIConversationContext,
)


class AIAgentBootstrapTests(TestCase):
    def test_bootstrap_creates_two_agents_and_configuration(self):
        result = bootstrap_ai_agents()

        self.assertEqual(result["agents_total"], 2)
        self.assertEqual(
            set(AIAgent.objects.values_list("code", flat=True)),
            {"machine_performance", "mining_knowledge"},
        )
        self.assertTrue(
            AIAgentCapability.objects.filter(
                agent__code="machine_performance",
                capability_code="kpi_query",
            ).exists()
        )
        self.assertTrue(
            AIAgentRoutingRule.objects.filter(
                rule_code="operational_and_recommendation",
                selected_agent="combined",
            ).exists()
        )

    def test_bootstrap_is_idempotent(self):
        bootstrap_ai_agents()
        counts = (
            AIAgent.objects.count(),
            AIAgentCapability.objects.count(),
            AIAgentRoutingRule.objects.count(),
        )
        bootstrap_ai_agents()
        self.assertEqual(
            counts,
            (
                AIAgent.objects.count(),
                AIAgentCapability.objects.count(),
                AIAgentRoutingRule.objects.count(),
            ),
        )


class AgentRouterTests(TestCase):
    def setUp(self):
        bootstrap_ai_agents()
        self.user = User.objects.create_user("router-user")

    def test_operational_question_routes_to_machine_performance(self):
        result = route_question(
            "What is the PA of Essakane 785 machines?",
            user=self.user,
        )
        self.assertEqual(result["selected_agent"], "machine_performance")
        self.assertEqual(result["method"], "deterministic")

    def test_best_practice_question_routes_to_mining_knowledge(self):
        result = route_question(
            "What are the best practices for preventive maintenance?",
            user=self.user,
        )
        self.assertEqual(result["selected_agent"], "mining_knowledge")

    def test_mixed_question_routes_to_combined(self):
        result = route_question(
            "Analyze the downtime drivers at Essakane and provide the relevant best practices.",
            user=self.user,
        )
        self.assertEqual(result["selected_agent"], "combined")

    def test_ambiguous_concept_requests_clarification(self):
        result = route_question("Explain availability.", user=self.user)
        self.assertEqual(result["selected_agent"], "clarification_required")
        self.assertTrue(result["requires_clarification"])

    def test_manual_agent_selection_is_respected(self):
        result = route_question(
            "What is availability?",
            user=self.user,
            manual_agent="mining_knowledge",
        )
        self.assertEqual(result["selected_agent"], "mining_knowledge")
        self.assertEqual(result["method"], "manual")

    def test_active_context_routes_follow_up(self):
        AIConversationContext.objects.create(
            user=self.user,
            conversation_id="conversation-1",
            active_agent="machine_performance",
            performance_context={"metric": "availability"},
        )
        result = route_question(
            "Show me its trend.",
            user=self.user,
            conversation_id="conversation-1",
        )
        self.assertEqual(result["selected_agent"], "machine_performance")

    def test_agent_contexts_remain_separate(self):
        update_agent_context(
            conversation_id="conversation-2",
            user=self.user,
            agent_code="machine_performance",
            intent="get_kpi_value",
            payload={"metric": "availability"},
        )
        update_agent_context(
            conversation_id="conversation-2",
            user=self.user,
            agent_code="mining_knowledge",
            intent="search_best_practice",
            payload={"topics": ["maintenance"]},
        )
        context = AIConversationContext.objects.get(
            conversation_id="conversation-2",
            user=self.user,
        )
        self.assertEqual(context.performance_context["metric"], "availability")
        self.assertEqual(context.knowledge_context["topics"], ["maintenance"])


class AIAgentAdministrationTests(TestCase):
    def setUp(self):
        bootstrap_ai_agents()
        self.admin = User.objects.create_superuser(
            username="agent-admin",
            email="agent-admin@example.com",
            password="secret",
        )
        self.user = User.objects.create_user("standard-user", password="secret")

    def test_admin_can_open_agent_page(self):
        client = Client()
        client.force_login(self.admin)
        response = client.get(reverse("ai-agents-home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Machine 360", count=0)
        self.assertContains(response, "AI Agents")

    def test_standard_user_cannot_open_agent_page(self):
        client = Client()
        client.force_login(self.user)
        response = client.get(reverse("ai-agents-home"))
        self.assertIn(response.status_code, (302, 403))

    def test_router_test_endpoint_returns_debug_information(self):
        client = Client()
        client.force_login(self.admin)
        response = client.post(
            reverse("ai-agent-router-test-api"),
            data='{"question":"What are the best practices for preventive maintenance?"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["routing"]["selected_agent"], "mining_knowledge")
        self.assertIn("reason", payload["routing"])

    def test_agent_list_api_exposes_bootstrap_agents(self):
        client = Client()
        client.force_login(self.admin)
        response = client.get(reverse("ai-agents-collection-api"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["agents"]), 2)

    @patch("reports.ai_agent_execution_service.process_user_question")
    def test_machine_agent_execution_is_logged(self, process_question):
        from .ai_agent_execution_service import execute_agent_question

        process_question.return_value = {
            "ok": True,
            "answer": "Availability is 90%.",
            "intent": {"metric": "availability", "filters": {}},
            "rows": [],
        }
        result = execute_agent_question(
            "Show availability for Essakane.",
            user=self.admin,
            conversation_id="execution-log-test",
            manual_agent="machine_performance",
            is_test=True,
        )
        self.assertTrue(result["ok"])
        self.assertTrue(
            AIAgentExecutionLog.objects.filter(
                selected_agent_code="machine_performance",
                is_test=True,
            ).exists()
        )
