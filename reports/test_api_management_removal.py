from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test import TestCase, SimpleTestCase
from django.urls import resolve, Resolver404

from .legacy_ai_service import legacy_ai
from .legacy_ai_types import LegacyAIError

REMOVED_MODELS = ('AIProvider', 'AIProviderCredential', 'AIProviderModel', 'AIUseCaseConfiguration',
                  'AIAgentProviderConfiguration', 'AIProviderUsageLog', 'AIProviderHealthLog',
                  'AIProviderCircuitState', 'AIProviderAuditLog')


class RemovedManagementTests(TestCase):
    def test_catalogue_models_and_tables_are_absent(self):
        tables = {name.casefold() for name in connection.introspection.table_names()}
        for name in REMOVED_MODELS:
            with self.subTest(model=name):
                with self.assertRaises(LookupError):
                    apps.get_model('reports', name)
                self.assertNotIn(name.casefold(), tables)
        self.assertNotIn('ai_agent_provider_configuration', tables)
        self.assertFalse(ContentType.objects.filter(app_label='reports', model__in=[name.lower() for name in REMOVED_MODELS]).exists())

    def test_all_former_routes_are_removed(self):
        for path in ('/ai-config/api-management/', '/api/ai/providers/', '/api/ai/providers/dashboard/',
                     '/api/ai/provider-models/', '/api/ai/provider-playground/test/',
                     '/api/ai/provider-health/check-all/', '/api/ai/provider-usage/', '/api/ai/use-case-routing/'):
            with self.subTest(path=path), self.assertRaises(Resolver404):
                resolve(path)

    def test_existing_config_and_chatbot_navigation_remain(self):
        user=User.objects.create_superuser('removal-test',password='synthetic-test-only')
        self.client.force_login(user)
        response=self.client.get('/ia-config/')
        self.assertEqual(response.status_code,200)
        self.assertNotContains(response,'API Management')
        self.assertContains(response,'AI Config')
        for path in ('/codex-chatbot/', '/business-review/command-center/', '/ia-config/agents/'):
            self.assertIsNotNone(resolve(path))


class LegacyDependencyTests(SimpleTestCase):
    @patch('reports.openai_service.get_openai_api_key',return_value='')
    def test_missing_credentials_fail_without_database_or_network(self, key):
        with self.assertRaises(LegacyAIError) as caught:
            legacy_ai.generate_text(use_case='test',messages=[])
        self.assertEqual(caught.exception.code,'AUTHENTICATION_ERROR')

    @patch('reports.legacy_ai_service.LegacyOpenAIAdapter')
    @patch('reports.openai_service.get_openai_model',return_value='synthetic-model')
    @patch('reports.openai_service.get_openai_api_key',return_value='synthetic-test-key')
    def test_remaining_calls_need_no_removed_tables(self,key,model,adapter):
        adapter.return_value.generate_text.return_value=SimpleNamespace(content='synthetic answer')
        result=legacy_ai.generate_text(use_case='test',messages=[{'role':'user','content':'test'}])
        self.assertEqual(result.content,'synthetic answer')
        self.assertEqual(adapter.return_value.generate_text.call_args.args[0].model,'synthetic-model')

    @patch('reports.legacy_ai_service.LegacyOpenAIAdapter')
    @patch('reports.openai_service.get_openai_model',return_value='synthetic-model')
    @patch('reports.openai_service.get_openai_api_key',return_value='synthetic-test-key')
    def test_invalid_structured_output_is_still_rejected(self,key,model,adapter):
        adapter.return_value.generate_structured_output.return_value=SimpleNamespace(structured_output={})
        with self.assertRaises(LegacyAIError) as caught:
            legacy_ai.generate_structured_output(use_case='test',messages=[],
                output_schema={'type':'object','required':['answer'],'properties':{'answer':{'type':'string'}}})
        self.assertEqual(caught.exception.code,'INVALID_STRUCTURED_OUTPUT')
