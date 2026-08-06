from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from unittest.mock import Mock, patch

from .models import (
    ResourceKnowledgeChunk,
    ResourceKnowledgeDocument,
    ResourceKnowledgeItem,
)
from .resource_knowledge_extraction_service import ExtractedPage, build_chunks
from .resource_knowledge_search_service import search_resource_knowledge
from .resource_knowledge_ai_service import extraction_model, extraction_reasoning_effort


class ResourceKnowledgeExtractionTests(TestCase):
    def test_sol_max_is_the_resource_extraction_default(self):
        self.assertEqual(extraction_model(), "gpt-5.6-sol")
        self.assertEqual(extraction_reasoning_effort(), "max")

    def test_chunks_keep_page_references_and_stable_hashes(self):
        pages = [
            ExtractedPage(1, "COOLING SYSTEM\n\nWater pump leakage inspection procedure."),
            ExtractedPage(2, "SAFETY\n\nStop the engine before inspection."),
        ]

        first = build_chunks(pages)
        second = build_chunks(pages)

        self.assertGreaterEqual(len(first), 1)
        self.assertEqual(first[0].page_start, 1)
        self.assertEqual(first[0].content_hash, second[0].content_hash)


class ResourceKnowledgeSearchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.document = ResourceKnowledgeDocument.objects.create(
            resource_id="water-pump-guide",
            relative_path="Maintenance/water-pump-guide.pdf",
            title="Water Pump Inspection Guide",
            filename="water-pump-guide.pdf",
            file_hash="a" * 64,
            status="Indexed",
        )
        cls.chunk = ResourceKnowledgeChunk.objects.create(
            document=cls.document,
            chunk_index=0,
            page_start=12,
            page_end=12,
            content="Inspect water pump leakage and bearing noise.",
            content_hash="b" * 64,
        )
        cls.validated = ResourceKnowledgeItem.objects.create(
            document=cls.document,
            chunk=cls.chunk,
            knowledge_key="c" * 64,
            title="Inspect water pump leakage",
            component="Water Pump",
            equipment_model="",
            symptom="Coolant leakage and bearing noise",
            recommendations=["Inspect the pump shaft seal."],
            source_excerpt="Inspect water pump leakage and bearing noise.",
            source_page=12,
            confidence=98,
            validation_status="Validated",
        )
        cls.draft = ResourceKnowledgeItem.objects.create(
            document=cls.document,
            chunk=cls.chunk,
            knowledge_key="d" * 64,
            title="Draft radiator recommendation",
            component="Radiator",
            symptom="Radiator overheating",
            source_excerpt="Draft radiator guidance.",
            confidence=70,
            validation_status="To Review",
        )

    def test_production_returns_only_validated_with_source(self):
        result = search_resource_knowledge(
            "water pump leakage",
            mode="Production",
            use_embeddings=False,
        )

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["results"][0]["id"], str(self.validated.id))
        self.assertEqual(result["results"][0]["source"]["page"], 12)

    def test_debug_can_return_to_review(self):
        result = search_resource_knowledge(
            "radiator overheating",
            mode="Debug",
            use_embeddings=False,
        )

        self.assertIn(str(self.draft.id), [item["id"] for item in result["results"]])

    def test_model_filter_keeps_generic_guidance(self):
        result = search_resource_knowledge(
            "water pump",
            filters={"model": "785"},
            mode="Production",
            use_embeddings=False,
        )

        self.assertEqual(result["count"], 1)


class ResourceKnowledgeAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_user(
            username="resource_admin",
            password="password",
            is_staff=True,
        )
        cls.user = get_user_model().objects.create_user(
            username="resource_viewer",
            password="password",
        )

    def test_admin_page_is_restricted(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("resource-knowledge-admin"))
        self.assertEqual(response.status_code, 403)

    def test_admin_page_renders(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("resource-knowledge-admin"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Business Knowledge Base")
        self.assertContains(response, "Preview")

    @patch("reports.resource_knowledge_views.start_index_job")
    def test_html_fallback_starts_creation(self, start_index_job):
        start_index_job.return_value = Mock(id="run-test")
        self.client.force_login(self.admin)

        response = self.client.post(reverse("resource-knowledge-rebuild"), {
            "with_ai": "true",
            "with_embeddings": "true",
        })

        self.assertRedirects(response, reverse("resource-knowledge-admin"))
        start_index_job.assert_called_once()
