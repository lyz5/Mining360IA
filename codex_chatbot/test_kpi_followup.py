from types import SimpleNamespace
from unittest.mock import patch
from django.test import SimpleTestCase
from .tools.performance_followup import needs_performance_context, context_from_evidence
from .tools.unified import unified_analysis
from .tools.quick_kpi import quick_kpi_answer


SCOPE={'period_code':'custom:2026-01-01:2026-08-31',
       'filters':{'minesite':'SNIM-Guelb','model':'789'}}


class KpiFollowupTests(SimpleTestCase):
    def test_short_followups_and_standalone_requests_are_distinguished(self):
        for question in ['Et le MTTR ?', 'le MTBF?', 'MTBS', 'Et le LPH ?',
                         'Et la disponibilité ?', 'And the MTTR?', 'What about fuel?',
                         'Donne le MTBF sur cette période']:
            self.assertTrue(needs_performance_context(question),question)
        for question in ['Donne le MTBF des 789 à SNIM-Guelb YTD',
                         "C'est quoi le MTBF ?",'What does MTTR mean?','Bonjour']:
            self.assertFalse(needs_performance_context(question),question)

    def execute(self,question,scope=SCOPE,filters=None,resolution=None,allowed=True):
        def result(user,params):
            return {'context':{'metric_code':params['metric'],'period_code':params['period'],
                               'period_label':'Période demandée','start_date':'2026-01-01',
                               'end_date':'2026-08-31','breakdown':params['breakdown'],
                               'filters':{k:params[k] for k in ('minesite','model') if k in params}},
                    'metric':{'raw_value':5.43,'formatted_value':'5.43 L/h' if params['metric']=='fuel' else '5.43 h'}}
        with patch('codex_chatbot.tools.unified.is_platform_admin',return_value=allowed), \
             patch('codex_chatbot.tools.unified.has_module_access',return_value=allowed), \
             patch('codex_chatbot.tools.unified.extract_intent',return_value={'filters':filters or {}}), \
             patch('codex_chatbot.tools.unified.resolve_minesite_from_question',return_value=resolution), \
             patch('codex_chatbot.tools.unified.performance_payload',side_effect=result) as provider:
            answer=unified_analysis(question,user=object(),inherited_context=scope)
        return answer,provider

    def test_followup_chain_keeps_scope_and_fetches_each_new_metric(self):
        scope=SCOPE
        for question,metric in [('Et le MTTR ?','mttr'),('Et le LPH ?','fuel'),
                                ('Et le MTBF ?','mtbf'),('Et le MTBS ?','mtbs'),
                                ('Et la disponibilité ?','availability')]:
            answer,provider=self.execute(question,scope)
            params=provider.call_args.args[1]
            self.assertEqual(params['metric'],metric)
            self.assertEqual(params['minesite'],'SNIM-Guelb')
            self.assertEqual(params['model'],'789')
            self.assertEqual(params['period'],SCOPE['period_code'])
            self.assertIsNotNone(quick_kpi_answer(question,answer))
            scope=context_from_evidence(answer)
            self.assertEqual(scope,SCOPE)

    def test_explicit_site_model_and_dates_override_only_requested_scope(self):
        site=SimpleNamespace(ambiguous=False,semantic_name='Fekola')
        answer,provider=self.execute('Et le MTTR des 777 à Fekola du 2026-07-01 au 2026-07-31 ?',
                                     filters={'model':'777'},resolution=site)
        params=provider.call_args.args[1]
        self.assertEqual((params['minesite'],params['model'],params['period']),
                         ('Fekola','777','custom:2026-07-01:2026-07-31'))

    def test_explicit_ytd_replaces_previous_custom_period(self):
        _,provider=self.execute('Et le MTTR en YTD ?',
                               scope={**SCOPE,'period_code':'custom:2026-07-01:2026-07-31'})
        self.assertEqual(provider.call_args.args[1]['period'],'ytd')

    def test_parser_default_ytd_does_not_override_previous_month(self):
        _,provider=self.execute('Et le LPH ?',filters={'period':'YTD'},
                               scope={**SCOPE,'period_code':'custom:2026-07-01:2026-07-31'})
        self.assertEqual(provider.call_args.args[1]['period'],'custom:2026-07-01:2026-07-31')

    def test_no_context_or_current_permission_never_queries_source(self):
        answer,provider=self.execute('Et le MTTR ?',scope=None)
        self.assertEqual(answer['answer_status'],'NEEDS_CLARIFICATION');provider.assert_not_called()
        answer,provider=self.execute('Et le LPH ?',allowed=False)
        self.assertEqual(answer['answer_status'],'ACCESS_RESTRICTED');provider.assert_not_called()
