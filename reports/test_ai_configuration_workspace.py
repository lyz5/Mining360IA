from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import AIConfigSection, AIQuestionExample


@override_settings(ENABLE_AI_CONFIG_WORKSPACE_REDESIGN="Production")
class AIConfigurationWorkspaceTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            "ai-config-admin", "ai-admin@example.com", "password"
        )
        self.client.force_login(self.admin)
        self.section = AIConfigSection.objects.create(
            code="workspace-performance", name="Workspace Performance"
        )
        for index in range(3):
            AIQuestionExample.objects.create(
                section=self.section,
                question_text=f"Availability question {index}",
                language="en",
                is_active=index != 2,
            )

    def test_workspace_is_default_and_keeps_all_entity_navigation(self):
        response = self.client.get(reverse("ia-config-home"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "reports/ia_config_workspace.html")
        self.assertContains(response, "Language &amp; Training")
        self.assertContains(response, "Semantic Model")
        self.assertContains(response, "Query &amp; Response")
        self.assertContains(response, "Business Governance")
        self.assertContains(response, "Test &amp; Diagnostics")
        self.assertContains(response, 'data-resource-type="recommended-actions"')

    def test_legacy_workspace_remains_available_for_rollback(self):
        response = self.client.get(reverse("ia-config-home"), {"legacy": "1"})

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "reports/ia_config.html")

    def test_sections_api_returns_readiness_summary(self):
        response = self.client.get(reverse("ia-config-sections-api"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        section = next(
            item for item in payload["sections"]
            if item["code"] == self.section.code
        )
        self.assertEqual(section["entity_counts"]["question-examples"], 3)
        self.assertIn(section["status"], {"ready", "needs_review"})
        self.assertEqual(payload["summary"]["total"], len(payload["sections"]))

    def test_entity_list_supports_ajax_pagination_and_active_filter(self):
        url = reverse(
            "ia-config-collection-api",
            kwargs={
                "section_code": self.section.code,
                "resource_type": "question-examples",
            },
        )
        response = self.client.get(
            url,
            {"page": 1, "page_size": 1, "active": "1", "q": "availability"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["items"]), 1)
        self.assertEqual(payload["pagination"]["count"], 2)
        self.assertTrue(payload["pagination"]["has_next"])

    def test_legacy_entity_contract_remains_unpaginated_without_parameters(self):
        response = self.client.get(
            reverse(
                "ia-config-collection-api",
                kwargs={
                    "section_code": self.section.code,
                    "resource_type": "question-examples",
                },
            )
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["items"]), 3)
        self.assertIsNone(payload["pagination"])
