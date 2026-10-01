from unittest.mock import patch
from django.test import SimpleTestCase, TestCase
from django.contrib.auth import get_user_model
from .tools.performance_followup import context_from_evidence, prior_performance_context
from .tools.unified import unified_analysis
from .tools.excellence_evidence import requested_views
from .general_conversation import looks_like_business_data_request

QUESTION = 'Donne moi les top downtimes drivers sur cette période'
CONTEXT = {'metric_code':'availability','period_code':'ytd','filters':{'minesite':'SNIM-Guelb','model':'789'}}


class DowntimeFollowupTests(SimpleTestCase):
    def test_plural_is_business_data_and_downtime_view(self):
        self.assertTrue(looks_like_business_data_request(QUESTION))
        self.assertIn('downtime_systems',requested_views(QUESTION))

    def test_no_previous_scope_requests_clarification(self):
        with patch('codex_chatbot.tools.unified.performance_payload') as provider:
            result=unified_analysis(QUESTION,user=object())
        self.assertEqual(result['answer_status'],'NEEDS_CLARIFICATION')
        provider.assert_not_called()

    def test_multiple_previous_periods_are_not_silently_combined(self):
        self.assertIsNone(context_from_evidence({'kind':'governed_answer','payloads':[
            {'context':CONTEXT},{'context':{**CONTEXT,'period_code':'custom:2026-08-01:2026-08-31'}}]}))

    @patch('codex_chatbot.tools.unified.is_platform_admin',return_value=True)
    @patch('codex_chatbot.tools.unified.extract_intent',return_value={'filters':{}})
    @patch('codex_chatbot.tools.unified.resolve_minesite_from_question',return_value=None)
    @patch('codex_chatbot.tools.unified.performance_payload')
    def test_inherited_scope_fetches_fresh_hours_in_requested_order(self,provider,resolve,extract,admin):
        scope={'period_code':'custom:2026-08-01:2026-08-31','filters':CONTEXT['filters']}
        provider.return_value={'context':{**CONTEXT,'period_code':scope['period_code'],'breakdown':'equipment'},
            'summary':{'equipment_count':1},'breakdown':[{'entity':'fixture','metric_value':.8,'downtime_hours':12.5}]}
        result=unified_analysis(QUESTION+' par équipement',user=object(),inherited_context=scope)
        params=provider.call_args.args[1]
        self.assertEqual(params['minesite'],'SNIM-Guelb')
        self.assertEqual(params['model'],'789')
        self.assertEqual(params['period'],scope['period_code'])
        self.assertEqual(params['ordering'],'downtime_desc')
        self.assertEqual(result['rows'][0]['metric'],'DOWNTIME')
        self.assertEqual(result['rows'][0]['value'],12.5)
        self.assertIn('causes',result['text'])

    @patch('codex_chatbot.tools.unified.is_platform_admin',return_value=False)
    @patch('codex_chatbot.tools.unified.has_module_access',return_value=False)
    @patch('codex_chatbot.tools.unified.performance_payload')
    def test_previous_scope_never_grants_current_permission(self,provider,access,admin):
        result=unified_analysis(QUESTION,user=object(),inherited_context=CONTEXT)
        self.assertEqual(result['answer_status'],'ACCESS_RESTRICTED')
        provider.assert_not_called()


class ConversationScopeTests(TestCase):
    def test_scope_stays_in_same_conversation_and_owner(self):
        from .models import CodexConversation,CodexRun,CodexEvidence
        user=get_user_model().objects.create_user('followup-user')
        other=get_user_model().objects.create_user('other-followup-user')
        c=CodexConversation.objects.create(owner=user)
        prior=CodexRun.objects.create(conversation=c,user=user,question='Availability')
        CodexEvidence.objects.create(run=prior,source_type='DATABASE_TABLE',value_json={'kind':'availability_summary','context':CONTEXT})
        current=CodexRun.objects.create(conversation=c,user=user,question=QUESTION)
        self.assertEqual(prior_performance_context(current)['filters'],CONTEXT['filters'])
        elsewhere=CodexConversation.objects.create(owner=user)
        isolated=CodexRun.objects.create(conversation=elsewhere,user=user,question=QUESTION)
        self.assertIsNone(prior_performance_context(isolated))
        wrong_owner=CodexRun.objects.create(conversation=c,user=other,question=QUESTION)
        self.assertIsNone(prior_performance_context(wrong_owner))

    def test_intervening_unrelated_request_does_not_restore_older_scope(self):
        from .models import CodexConversation,CodexRun,CodexEvidence
        user=get_user_model().objects.create_user('interrupted-followup-user')
        c=CodexConversation.objects.create(owner=user)
        prior=CodexRun.objects.create(conversation=c,user=user,question='Availability')
        CodexEvidence.objects.create(run=prior,source_type='DATABASE_TABLE',value_json={'kind':'availability_summary','context':CONTEXT})
        CodexRun.objects.create(conversation=c,user=user,question='Other question')
        current=CodexRun.objects.create(conversation=c,user=user,question=QUESTION)
        self.assertIsNone(prior_performance_context(current))
