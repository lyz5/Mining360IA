from django.apps import apps
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test import TestCase
from django.urls import resolve, Resolver404
from .models import VoiceTranscriptionLog

REMOVED=('OpenAIModelPricing','OpenAIUsageLog','OpenAICostSnapshot','OpenAIUsageSnapshot','OpenAIBudget','OpenAICreditSnapshot')


class UsageRetirementTests(TestCase):
    def test_schema_has_no_usage_catalogue(self):
        tables=connection.introspection.table_names()
        for name in REMOVED:
            self.assertNotIn(name,tables)
            with self.assertRaises(LookupError):apps.get_model('reports',name)
        self.assertFalse(ContentType.objects.filter(app_label='reports',model__in=[n.lower() for n in REMOVED]).exists())
        self.assertNotIn('openai_usage_log',{f.name for f in VoiceTranscriptionLog._meta.fields})

    def test_routes_and_telemetry_middleware_removed(self):
        for path in ('/config/openai-usage/','/api/admin/openai-usage/dashboard/',
                     '/api/admin/openai-usage/settings/','/api/admin/openai-usage/synchronize/',
                     '/api/admin/openai-usage/export/csv/'):
            with self.subTest(path=path), self.assertRaises(Resolver404):resolve(path)
        self.assertFalse(any('openai_usage' in m for m in settings.MIDDLEWARE))

    def test_config_navigation_preserves_remaining_products(self):
        user=User.objects.create_superuser('usage-removal',password='synthetic-test-only')
        self.client.force_login(user)
        response=self.client.get('/ia-config/')
        self.assertEqual(response.status_code,200)
        self.assertNotContains(response,'OpenAI API Usage')
        self.assertNotContains(response,'API Management')
        self.assertContains(response,'AI Config')
