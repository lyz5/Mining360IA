from unittest.mock import Mock, patch
from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from reports.models import ResourceKnowledgeConfiguration, ResourceKnowledgeItem, ResourceKnowledgeIndexRun
from reports.resource_knowledge_index_service import _save_deterministic_knowledge, start_index_job, index_resource
from reports.resource_knowledge_views import knowledge_rebuild_api

class KnowledgeResetTests(TestCase):
    def setUp(self):
        ResourceKnowledgeConfiguration.objects.create(name="Best Practices Bootstrap", is_active=False)
    def test_fragment_is_not_knowledge(self):
        self.assertEqual(_save_deterministic_knowledge(Mock(), Mock(content="Maintenance and")), 0)
        self.assertEqual(ResourceKnowledgeItem.objects.count(), 0)
    def test_disabled_job_cannot_start(self):
        with self.assertRaisesMessage(RuntimeError, "complete source review"):
            start_index_job()
        self.assertEqual(ResourceKnowledgeIndexRun.objects.count(), 0)
    def test_disabled_direct_index_cannot_read_or_write(self):
        with patch("reports.resource_knowledge_index_service.get_resource_path") as source:
            with self.assertRaises(RuntimeError):
                index_resource(Mock())
            source.assert_not_called()
    def test_rebuild_api_returns_clear_conflict(self):
        request=RequestFactory().post("/resources/knowledge/api/rebuild/", data={}, content_type="application/json")
        request.user=get_user_model().objects.create_superuser(username="kb-reset-admin",password="test-password")
        self.assertEqual(knowledge_rebuild_api(request).status_code,409)
