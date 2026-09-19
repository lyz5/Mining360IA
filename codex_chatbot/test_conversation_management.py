import json
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from reports.models import AIConversation, AIConversationMessage
from .history_import import import_history
from .models import CodexConversation, CodexMessage, CodexRun


@override_settings(ENABLE_CODEX_CHATBOT="Admin Only", CODEX_CHATBOT_APP_SERVER_ENABLED=False)
class ConversationManagementTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('owner',is_staff=True,is_superuser=True)
        self.other = get_user_model().objects.create_user('other',is_staff=True,is_superuser=True)
        self.conversation = CodexConversation.objects.create(owner=self.user,title='Original')
        self.url = reverse('codex_chatbot:conversation-api',args=[self.conversation.pk])
        self.client.force_login(self.user)

    def patch(self, payload):
        return self.client.patch(self.url,data=json.dumps(payload),content_type='application/json')

    def test_rename_archive_restore(self):
        self.assertEqual(self.patch({'title':'Équipements à vérifier'}).status_code,200)
        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.title,'Équipements à vérifier')
        self.patch({'status':'ARCHIVED'});self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.status,'ARCHIVED')
        self.patch({'status':'ACTIVE'});self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.status,'ACTIVE')
        for payload in ({'title':''},{'title':'x'*181},{'status':'DELETED'},[]):
            self.assertEqual(self.patch(payload).status_code,400)

    def test_other_owner_cannot_modify_delete(self):
        self.client.force_login(self.other)
        self.assertEqual(self.patch({'title':'forbidden'}).status_code,404)
        self.assertEqual(self.client.delete(self.url).status_code,404)
        self.assertTrue(CodexConversation.objects.filter(pk=self.conversation.pk).exists())

    def test_delete_cascades_and_cannot_reimport_original(self):
        original=AIConversation.objects.create(user=self.user,title='Legacy')
        AIConversationMessage.objects.create(conversation=original,role='user',content='ancien')
        import_history()
        copied=CodexConversation.objects.get(legacy_conversation_id=original.pk)
        url=reverse('codex_chatbot:conversation-api',args=[copied.pk])
        self.assertEqual(self.client.delete(url).status_code,200)
        self.assertFalse(AIConversation.objects.filter(pk=original.pk).exists())
        self.assertFalse(CodexMessage.objects.filter(conversation_id=copied.pk).exists())
        self.assertEqual(import_history(),{'conversations':0,'messages':0})
        self.assertEqual(self.client.get(url).status_code,404)

    def test_running_conversation_must_be_cancelled_first(self):
        run=CodexRun.objects.create(conversation=self.conversation,user=self.user,status='RUNNING',question='test')
        self.assertEqual(self.client.delete(self.url).status_code,409)
        run.status='CANCELLED';run.save()
        self.assertEqual(self.client.delete(self.url).status_code,200)
        self.assertFalse(CodexRun.objects.filter(pk=run.pk).exists())

    def test_worker_completion_does_not_overwrite_rename_or_archive(self):
        from .orchestrator import execute_persisted_run
        run=CodexRun.objects.create(conversation=self.conversation,user=self.user,status='QUEUED',question='backorder')
        # Simulate an action after the worker loaded its conversation instance.
        CodexConversation.objects.filter(pk=self.conversation.pk).update(title='Nouveau titre',status='ARCHIVED')
        execute_persisted_run(run)
        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.title,'Nouveau titre')
        self.assertEqual(self.conversation.status,'ARCHIVED')
