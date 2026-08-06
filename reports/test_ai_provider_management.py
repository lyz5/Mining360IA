from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase

from .ai_provider_bootstrap_service import bootstrap_ai_providers
from .ai_provider_gateway_service import AIProviderGatewayService
from .ai_provider_routing_service import ProviderSelection
from .ai_provider_types import AIProviderError, AIProviderResponse
from .ai_providers.base import BaseAIProviderAdapter
from .models import (
    AIAgent,
    AIAgentProviderConfiguration,
    AIProvider,
    AIProviderCredential,
    AIProviderModel,
    AIProviderUsageLog,
    AIUseCaseConfiguration,
)


class ProviderBootstrapTests(TestCase):
    def test_bootstrap_creates_four_ordered_providers_and_openai_default(self):
        result = bootstrap_ai_providers()

        self.assertEqual(result["providers"], 4)
        self.assertEqual(
            list(AIProvider.objects.order_by("-priority").values_list("code", flat=True)),
            ["openai", "anthropic_claude", "google_gemini", "glm_5"],
        )
        openai = AIProvider.objects.get(code="openai")
        self.assertTrue(openai.is_default)
        self.assertEqual(openai.priority, 100)
        self.assertTrue(
            AIUseCaseConfiguration.objects.filter(
                use_case_code="smcs_comment_classification",
                primary_provider=openai,
            ).exists()
        )

    def test_bootstrap_is_idempotent(self):
        bootstrap_ai_providers()
        counts = (
            AIProvider.objects.count(),
            AIProviderModel.objects.count(),
            AIUseCaseConfiguration.objects.count(),
        )
        bootstrap_ai_providers()
        self.assertEqual(
            counts,
            (
                AIProvider.objects.count(),
                AIProviderModel.objects.count(),
                AIUseCaseConfiguration.objects.count(),
            ),
        )

    def test_unconfigured_secondary_providers_are_inactive(self):
        bootstrap_ai_providers()
        self.assertFalse(AIProvider.objects.get(code="anthropic_claude").active)
        self.assertFalse(AIProvider.objects.get(code="google_gemini").active)
        self.assertFalse(AIProvider.objects.get(code="glm_5").active)


class _SuccessAdapter:
    def __init__(self, provider):
        self.provider = provider

    def generate_text(self, request):
        return AIProviderResponse(
            request_id=request.request_id,
            provider=self.provider.code,
            model=request.model,
            content="OK",
            usage={"input_tokens": 2, "output_tokens": 1, "cached_tokens": 0, "total_tokens": 3},
            latency_ms=12,
        )

    def normalize_error(self, exception):
        return exception


class _FailingAdapter(_SuccessAdapter):
    def __init__(self, provider, error):
        super().__init__(provider)
        self.error = error

    def generate_text(self, request):
        raise self.error


class ProviderGatewayTests(TestCase):
    def setUp(self):
        self.primary = AIProvider.objects.create(
            code="primary",
            name="Primary",
            provider_type="custom",
            priority=100,
            is_default=True,
            active=True,
            status="active",
            capabilities_json=["text_generation"],
        )
        self.fallback = AIProvider.objects.create(
            code="fallback",
            name="Fallback",
            provider_type="custom",
            priority=90,
            active=True,
            status="active",
            capabilities_json=["text_generation"],
        )
        self.primary_model = AIProviderModel.objects.create(
            provider=self.primary,
            model_code="primary-model",
            display_name="Primary Model",
            capabilities_json=["text_generation"],
            is_default_for_provider=True,
        )
        self.fallback_model = AIProviderModel.objects.create(
            provider=self.fallback,
            model_code="fallback-model",
            display_name="Fallback Model",
            capabilities_json=["text_generation"],
            is_default_for_provider=True,
        )
        self.use_case = AIUseCaseConfiguration.objects.create(
            use_case_code="test_generation",
            display_name="Test Generation",
            primary_provider=self.primary,
            primary_model=self.primary_model,
            fallback_enabled=True,
            required_capabilities_json=["text_generation"],
        )
        self.selections = [
            ProviderSelection(self.primary, self.primary_model, self.use_case, "primary"),
            ProviderSelection(self.fallback, self.fallback_model, self.use_case, "primary"),
        ]
        self.gateway = AIProviderGatewayService()

    @patch("reports.ai_provider_gateway_service.provider_secret", return_value="secret")
    @patch("reports.ai_provider_gateway_service.provider_routing_service.select")
    @patch("reports.ai_provider_gateway_service.adapter_registry.create")
    def test_success_returns_normalized_response_and_tracks_usage(
        self, create_adapter, select, _secret
    ):
        select.return_value = self.selections
        create_adapter.return_value = _SuccessAdapter(self.primary)

        response = self.gateway.generate_text(
            use_case="test_generation",
            messages=[{"role": "user", "content": "test"}],
            options={"retry_count": 0},
        )

        self.assertEqual(response.content, "OK")
        self.assertEqual(response.provider, "primary")
        self.assertFalse(response.fallback_used)
        self.assertTrue(
            AIProviderUsageLog.objects.filter(
                provider_code="primary",
                status="completed",
                total_tokens=3,
            ).exists()
        )

    @patch("reports.ai_provider_gateway_service.provider_secret", return_value="secret")
    @patch("reports.ai_provider_gateway_service.provider_routing_service.select")
    @patch("reports.ai_provider_gateway_service.adapter_registry.create")
    def test_timeout_falls_back_to_secondary_provider(
        self, create_adapter, select, _secret
    ):
        select.return_value = self.selections
        create_adapter.side_effect = [
            _FailingAdapter(self.primary, AIProviderError("TIMEOUT", "slow")),
            _SuccessAdapter(self.fallback),
        ]

        response = self.gateway.generate_text(
            use_case="test_generation",
            messages=[{"role": "user", "content": "test"}],
            options={"retry_count": 0},
        )

        self.assertEqual(response.provider, "fallback")
        self.assertTrue(response.fallback_used)
        self.assertEqual(response.attempts[0]["error_code"], "TIMEOUT")

    @patch("reports.ai_provider_gateway_service.provider_secret", return_value="secret")
    @patch("reports.ai_provider_gateway_service.provider_routing_service.select")
    @patch("reports.ai_provider_gateway_service.adapter_registry.create")
    def test_authentication_error_does_not_fall_back(
        self, create_adapter, select, _secret
    ):
        select.return_value = self.selections
        create_adapter.return_value = _FailingAdapter(
            self.primary,
            AIProviderError(
                "AUTHENTICATION_ERROR",
                "invalid key",
                retryable=False,
            ),
        )

        with self.assertRaises(AIProviderError) as captured:
            self.gateway.generate_text(
                use_case="test_generation",
                messages=[{"role": "user", "content": "test"}],
                options={"retry_count": 0},
            )
        self.assertEqual(captured.exception.code, "AUTHENTICATION_ERROR")
        self.assertEqual(create_adapter.call_count, 1)


class ProviderErrorNormalizationTests(TestCase):
    def test_sdk_connection_error_is_retryable(self):
        class APIConnectionError(Exception):
            pass

        provider = AIProvider(
            code="openai",
            name="OpenAI",
            provider_type="openai",
        )
        error = BaseAIProviderAdapter(provider, "secret").normalize_error(
            APIConnectionError("Connection error.")
        )

        self.assertEqual(error.code, "CONNECTION_ERROR")
        self.assertTrue(error.retryable)


class ProviderAdministrationTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="provider-admin",
            email="admin@example.com",
            password="password",
        )
        self.user = User.objects.create_user("provider-user", password="password")
        self.client = Client()
        bootstrap_ai_providers()

    def test_api_management_requires_admin(self):
        self.client.force_login(self.user)
        response = self.client.get("/ai-config/api-management/")
        self.assertIn(response.status_code, {302, 403})

    def test_api_management_page_and_masked_credentials(self):
        openai = AIProvider.objects.get(code="openai")
        AIProviderCredential.objects.filter(provider=openai).update(
            encrypted_value="encrypted-value",
            last_four_characters="ABCD",
        )
        self.client.force_login(self.admin)
        response = self.client.get("/ai-config/api-management/")
        self.assertEqual(response.status_code, 200)
        response = self.client.get("/api/ai/providers/")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        provider = next(item for item in payload["items"] if item["code"] == "openai")
        self.assertNotIn("encrypted_value", provider)
        self.assertNotIn("secret", str(provider).lower())

    def test_agent_provider_override_can_be_saved(self):
        agent = AIAgent.objects.create(
            code="test-agent",
            name="Test Agent",
            agent_type="machine_performance",
        )
        openai = AIProvider.objects.get(code="openai")
        use_case = AIUseCaseConfiguration.objects.get(
            use_case_code="machine_performance_response"
        )
        model = AIProviderModel.objects.filter(provider=openai).first()
        self.client.force_login(self.admin)

        response = self.client.post(
            f"/ia-config/agents/api/{agent.id}/providers/",
            data={
                "use_case_id": use_case.id,
                "provider_id": openai.id,
                "model_id": model.id,
                "priority": 120,
                "fallback_enabled": True,
                "active": True,
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            AIAgentProviderConfiguration.objects.filter(
                agent=agent,
                use_case=use_case,
                provider=openai,
                priority=120,
            ).exists()
        )

    def test_provider_credential_page_encrypts_and_activates_provider(self):
        provider = AIProvider.objects.get(code="glm_5")
        self.client.force_login(self.admin)
        page_url = f"/ai-config/api-management/providers/{provider.id}/credential/"

        response = self.client.get(page_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "GLM-5 Credential")

        response = self.client.post(
            page_url,
            {"credential": "glm-secret-value-ABCD", "activate": "on"},
        )
        self.assertEqual(response.status_code, 302)
        provider.refresh_from_db()
        credential = provider.credentials.get(active=True)
        self.assertTrue(provider.active)
        self.assertEqual(provider.status, "active")
        self.assertNotEqual(credential.encrypted_value, "glm-secret-value-ABCD")
        self.assertEqual(credential.last_four_characters, "ABCD")

    def test_provider_test_page_explains_missing_model_and_model_can_be_added(self):
        provider = AIProvider.objects.get(code="glm_5")
        self.client.force_login(self.admin)
        test_url = f"/ai-config/api-management/providers/{provider.id}/test/"
        model_url = f"/ai-config/api-management/providers/{provider.id}/models/add/"

        response = self.client.get(test_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No active model is configured")

        response = self.client.post(
            model_url,
            {
                "model_code": "glm-test-model",
                "display_name": "GLM Test Model",
                "maximum_output_tokens": 4096,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            AIProviderModel.objects.filter(
                provider=provider,
                model_code="glm-test-model",
                active=True,
                is_default_for_provider=True,
            ).exists()
        )

    def test_provider_can_be_deactivated_and_activated_from_server_page(self):
        provider = AIProvider.objects.get(code="openai")
        self.client.force_login(self.admin)
        url = f"/ai-config/api-management/providers/{provider.id}/status/"

        response = self.client.post(url, {"active": "0"})
        self.assertEqual(response.status_code, 302)
        provider.refresh_from_db()
        self.assertFalse(provider.active)
        self.assertEqual(provider.status, "inactive")

        response = self.client.post(url, {"active": "1"})
        self.assertEqual(response.status_code, 302)
        provider.refresh_from_db()
        self.assertTrue(provider.active)
        self.assertEqual(provider.status, "active")
