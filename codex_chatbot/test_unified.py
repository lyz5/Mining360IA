import json
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from reports.models import AIConversation, AIConversationMessage, AIConversationArtifact, PlatformUser
from .models import CodexConversation, CodexMessage
from .history_import import import_history
from .tools.unified import unified_analysis
from .access import chatbot_access_allowed


@override_settings(ENABLE_CODEX_CHATBOT="Admin Only", CODEX_CHATBOT_APP_SERVER_ENABLED=False)
class UnifiedChatTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("owner", is_superuser=True, is_staff=True)
        self.other = get_user_model().objects.create_user("other", is_superuser=True, is_staff=True)
        self.client.force_login(self.user)

    def test_history_idempotency_and_ownership(self):
        original = AIConversation.objects.create(user=self.user, title="Équipements à vérifier", status="archived",
                                                conversation_context_json={"site":"Mine École"})
        msg = AIConversationMessage.objects.create(conversation=original, role="assistant", content="État vérifié")
        AIConversationArtifact.objects.create(conversation=original, message=msg, title="Pièces", artifact_type="table",
                                              payload_json={"rows":[{"value":42}]})
        self.assertEqual(import_history(), {"conversations":1,"messages":1})
        self.assertEqual(import_history(), {"conversations":0,"messages":0})
        copied = CodexConversation.objects.get(legacy_conversation_id=original.pk)
        self.assertEqual(copied.owner, self.user)
        self.assertEqual(copied.status, "ARCHIVED")
        self.assertEqual(copied.created_at, original.created_at)
        self.assertEqual(CodexMessage.objects.get(legacy_message_id=msg.pk).created_at, msg.created_at)
        self.assertEqual(copied.legacy_context["artifacts"][0]["payload"]["rows"][0]["value"],42)
        self.assertEqual(AIConversationMessage.objects.get(pk=msg.pk).content, "État vérifié")
        self.assertRedirects(self.client.get(reverse('ai-conversation-page',args=[original.pk])),
                             reverse('codex_chatbot:conversation',args=[copied.pk]),fetch_redirect_response=False)
        download=reverse('codex_chatbot:history-download',args=[copied.pk])
        self.assertEqual(self.client.get(download).status_code,200)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(download).status_code,404)
        self.assertEqual(self.client.get(reverse('ai-conversation-page',args=[original.pk])).status_code,404)
        self.assertEqual(self.client.post(reverse('codex_chatbot:history-status',args=[copied.pk]),{'status':'ACTIVE'}).status_code,404)

    def test_old_generation_is_retired_and_only_one_menu(self):
        self.assertEqual(self.client.post(reverse('ai-ask'),data=json.dumps({'question':'bonjour'}),content_type='application/json').status_code,410)
        self.assertRedirects(self.client.get(reverse('ai-home')),reverse('codex_chatbot:home'),fetch_redirect_response=False)
        response=self.client.get(reverse('codex_chatbot:home'))
        self.assertNotContains(response,'href="/ai/"')
        from urllib.parse import parse_qs, urlsplit
        response=self.client.get(reverse('ai-home'),{'draft':'MTBF à Fékola YTD'})
        self.assertEqual(parse_qs(urlsplit(response.url).query)['draft'],['MTBF à Fékola YTD'])

    def test_legacy_ai_permission_preserved_without_granting_reporting(self):
        user=get_user_model().objects.create_user('legacy')
        PlatformUser.objects.create(django_user=user,azure_ad_id='legacy',user_principal_name='legacy@example.test',
                                    display_name='Legacy',can_access_ai=True,can_access_reporting=False)
        self.assertTrue(chatbot_access_allowed(user))
        with patch('codex_chatbot.tools.unified.HomepageAvailabilityService') as service:
            result=unified_analysis('MTBF YTD',user=user)
        self.assertEqual(result['answer_status'],'ACCESS_RESTRICTED')
        service.assert_not_called()
        with override_settings(ENABLE_CODEX_CHATBOT='Disabled'):
            self.assertFalse(chatbot_access_allowed(user))

    @patch('codex_chatbot.tools.unified.resolve_minesite_from_question',return_value=None)
    @patch('codex_chatbot.tools.unified.extract_intent',return_value={'filters':{'period':'ytd'}})
    @patch('codex_chatbot.tools.unified.HomepageAvailabilityService')
    def test_multiple_metrics_are_read_from_official_services(self, service, extract, resolve):
        service.return_value.get.return_value={'metric':{'raw_value':12,'formatted_value':'12 h'},'context':{'period_label':'YTD'}}
        result=unified_analysis('MTBF et MTTR YTD',user=self.user)
        self.assertEqual([r['metric'] for r in result['rows']],['MTBF','MTTR'])
        self.assertEqual(service.return_value.get.call_count,2)
        extract.assert_called_once_with('MTBF et MTTR YTD','performance',allow_llm=False)
        service.return_value.get.return_value={'metric':{'raw_value':None,'formatted_value':None}}
        self.assertEqual(unified_analysis('MTBF YTD',user=self.user)['answer_status'],'PARTIALLY_ANSWERABLE')

    @patch('codex_chatbot.tools.unified.search_resource_knowledge',return_value={'results':[]})
    def test_document_search_never_calls_embedding_api(self, search):
        result=unified_analysis('documentation maintenance',user=self.user)
        self.assertEqual(result['answer_status'],'NEEDS_CLARIFICATION')
        self.assertFalse(search.call_args.kwargs['use_embeddings'])

    def test_archive_and_restore(self):
        c=CodexConversation.objects.create(owner=self.user,title='test')
        url=reverse('codex_chatbot:history-status',args=[c.pk])
        self.assertEqual(self.client.post(url,{'status':'ARCHIVED'}).status_code,302)
        c.refresh_from_db();self.assertEqual(c.status,'ARCHIVED')
        self.assertContains(self.client.get(reverse('codex_chatbot:home')+'?history=archived'),c.title)
        self.client.post(url,{'status':'ACTIVE'});c.refresh_from_db();self.assertEqual(c.status,'ACTIVE')

    @patch('codex_chatbot.orchestrator.unified_analysis', return_value={
        'kind':'governed_answer','answer_status':'ACCESS_RESTRICTED','text':'Accès refusé.'})
    @patch('codex_chatbot.orchestrator._compose_with_codex')
    def test_restricted_evidence_is_not_persisted_or_sent_to_codex(self, compose, analysis):
        from .orchestrator import ask
        from .models import CodexEvidence
        result=ask(user=self.user,question='MTBF YTD')
        self.assertEqual(result['message']['answer_status'],'ACCESS_RESTRICTED')
        self.assertEqual(CodexEvidence.objects.count(),0)
        compose.assert_not_called()

    @patch('reports.intent_extractor_service.openai_extract_intent',side_effect=AssertionError('Legacy LLM forbidden'))
    def test_real_intent_extraction_can_run_without_api(self, legacy):
        from reports.intent_extractor_service import extract_intent
        self.assertIsInstance(extract_intent('MTBF YTD','performance',allow_llm=False),dict)
        legacy.assert_not_called()

    @patch('codex_chatbot.orchestrator.unified_analysis', return_value={
        'kind':'governed_answer','answer_status':'ANSWERABLE','text':'MTBF : 12 h',
        'rows':[{'metric':'MTBF','period':'YTD','value':12,'formatted_value':'12 h'}]})
    def test_unified_response_and_csv_use_persisted_metrics(self, analysis):
        import tempfile
        from .orchestrator import ask
        from .models import CodexRun
        from .fleet_export import create_fleet_csv, artifact_path
        result=ask(user=self.user,question='MTBF YTD')
        self.assertEqual(result['message']['content'],'MTBF : 12 h')
        with tempfile.TemporaryDirectory() as folder, override_settings(CODEX_CHATBOT_ARTIFACT_ROOT=folder):
            artifact=create_fleet_csv(CodexRun.objects.get(pk=result['run_id']))
            csv=artifact_path(artifact).read_text(encoding='utf-8-sig')
            self.assertIn('metric,period,formatted_value,value',csv)
            self.assertIn('MTBF,YTD,12 h,12',csv)
