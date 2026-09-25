import json
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from .models import ResourceKnowledgeDocument, ResourceKnowledgeItem

class SimpleKnowledgeReviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin=get_user_model().objects.create_superuser(username='review-admin',password='test-only-password')
        cls.regular=get_user_model().objects.create_user(username='review-user',password='test-only-password')
        cls.doc=ResourceKnowledgeDocument.objects.create(resource_id='guide.pdf',relative_path='guide.pdf',title='Brake Best Practice',filename='guide.pdf',file_hash='a'*64,status='Indexed')
        cls.items=[ResourceKnowledgeItem.objects.create(document=cls.doc,knowledge_key=f'{i:064x}',title=f'Knowledge {i:03}',source_page=12,source_excerpt='Check the baseline before interpreting wear.',validation_status='To Review') for i in range(28)]
    def setUp(self):
        self.client.force_login(self.admin)
    def test_four_columns_and_every_record_reachable(self):
        url=reverse('resource-knowledge-admin')
        first=self.client.get(url)
        self.assertEqual(first.status_code,200)
        self.assertEqual(len(first.context['knowledge_page']),25)
        self.assertEqual(first.context['knowledge_page'].paginator.count,28)
        for label in ('Best Practice','Identified Knowledge','Page Details','Validate / Reject'):
            self.assertContains(first,label)
        self.assertNotContains(first,'Build Knowledge')
        self.assertNotContains(first,'Test RAG')
        self.assertNotContains(first,'OpenAI calls')
        second=self.client.get(url,{'page':2})
        self.assertEqual(len(second.context['knowledge_page']),3)
        self.assertFalse(set(i.pk for i in first.context['knowledge_page']) & set(i.pk for i in second.context['knowledge_page']))
    def test_search_and_status_filter_apply_to_knowledge(self):
        self.items[0].validation_status='Rejected';self.items[0].save()
        response=self.client.get(reverse('resource-knowledge-admin'),{'q':'Knowledge 000','status':'Rejected'})
        self.assertEqual(response.context['knowledge_page'].paginator.count,1)
        self.assertEqual(response.context['knowledge_page'][0].pk,self.items[0].pk)
        response=self.client.get(reverse('resource-knowledge-admin'),{'q':'baseline','status':'To Review'})
        self.assertEqual(response.context['knowledge_page'].paginator.count,27)
    def test_hidden_documents_and_items_excluded(self):
        self.items[0].is_active=False;self.items[0].save()
        self.assertEqual(self.client.get(reverse('resource-knowledge-admin')).context['knowledge_page'].paginator.count,27)
        self.doc.is_active=False;self.doc.save()
        self.assertEqual(self.client.get(reverse('resource-knowledge-admin')).context['knowledge_page'].paginator.count,0)
    def test_source_link_targets_exact_pdf_page(self):
        data=self.client.get(reverse('resource-knowledge-item',args=[self.items[0].pk])).json()
        self.assertEqual(data['item']['source']['url'],reverse('resource-file',args=[self.doc.resource_id])+'#page=12')
    def test_validate_and_reject_one_item_preserves_others(self):
        item=self.items[0];url=reverse('resource-knowledge-item',args=[item.pk])
        for status in ('Validated','Rejected'):
            response=self.client.post(url,json.dumps({'validation_status':status}),content_type='application/json')
            self.assertEqual(response.status_code,200)
            item.refresh_from_db();self.assertEqual(item.validation_status,status)
            self.assertEqual(item.validated_by_id,self.admin.pk if status=='Validated' else None)
            self.assertEqual(item.validated_at is not None,status=='Validated')
        self.assertEqual(ResourceKnowledgeItem.objects.filter(validation_status='To Review').count(),27)
    def test_non_admin_cannot_read_or_validate(self):
        self.client.force_login(self.regular)
        self.assertEqual(self.client.get(reverse('resource-knowledge-admin')).status_code,403)
        response=self.client.post(reverse('resource-knowledge-item',args=[self.items[0].pk]),json.dumps({'validation_status':'Validated'}),content_type='application/json')
        self.assertEqual(response.status_code,403)
        self.items[0].refresh_from_db();self.assertEqual(self.items[0].validation_status,'To Review')