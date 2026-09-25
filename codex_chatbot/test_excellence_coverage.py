from unittest.mock import patch
from django.test import SimpleTestCase, TestCase
from django.contrib.auth import get_user_model
from .tools.excellence_evidence import requested_views, evidence_sections, unavailable_views
from .tools.unified import unified_analysis


class ExcellenceEvidenceTests(SimpleTestCase):
    def test_simple_kpi_does_not_request_fleet_details(self):
        self.assertNotIn('details',requested_views('MTBF des équipements Fekola en YTD'))
        self.assertIn('details',requested_views('Fuel details by equipment'))

    def test_all_fuel_sections_are_preserved_without_recalculation(self):
        payload={'context':{'period_label':'YTD'},'metric':{'comparison':{'delta_value':-2},'benchmark_formatted':'42 L/h'},
            'trend':[{'period':'2026-01','formatted_value':'43 L/h'}],
            'distribution':[{'lph':60,'count':3,'percentage':75}],
            'statistics':{'median':47.25},'equipment':[{'equipment':'A','lph':49.2}],
            'decision_support':{'lowest_observed':[{'entity':'A','formatted_value':'49.2 L/h'}]},
            'summary':{'equipment_count':4},'data_quality':{'latest_available_date':'2026-01-31'}}
        views={'trend','distribution','statistics','ranking','details','comparison','summary','quality'}
        tables=evidence_sections(payload,'fuel',views)
        self.assertFalse(unavailable_views(payload,'fuel',views))
        self.assertEqual(next(t for t in tables if 'Statistics' in t['title'])['rows'][0]['value'],47.25)
        self.assertEqual(next(t for t in tables if 'Trend' in t['title'])['rows'],payload['trend'])

    def test_truncation_is_explicit(self):
        payload={'equipment':[{'equipment':str(i),'lph':i} for i in range(120)]}
        table=evidence_sections(payload,'fuel',{'details'})[0]
        self.assertEqual(len(table['rows']),100)
        self.assertEqual(table['total_rows'],120)
        self.assertTrue(table['truncated'])

    def test_percentage_target_is_not_presented_as_mtbf_target(self):
        payload={'metric':{'target_raw':0.85,'target_formatted':'85%'}}
        self.assertEqual(evidence_sections(payload,'mtbf',{'target'}),[])
        self.assertEqual(unavailable_views(payload,'mtbf',{'target'}),['target'])

    def test_downtime_drivers_are_measured_hours_not_root_causes(self):
        views=requested_views('Show top downtime drivers affecting Availability at Fekola YTD')
        self.assertIn('downtime',views)
        tables=evidence_sections({'breakdown':[{'entity':'A','downtime_hours':5}]},'availability',{'downtime'})
        self.assertIn('not root causes',tables[0]['title'])
        self.assertEqual(tables[0]['rows'][0]['downtime_hours'],5)


class ExcellenceRoutingTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_user('excellence-reader',is_superuser=True)

    @patch('codex_chatbot.tools.unified.resolve_minesite_from_question',return_value=None)
    @patch('codex_chatbot.tools.unified.extract_intent',return_value={'filters':{'period':'ytd'}})
    @patch('codex_chatbot.tools.unified.performance_payload')
    def test_fuel_statistics_are_sent_with_evidence(self,provider,extract,resolve):
        provider.return_value={'metric':{'raw_value':42,'formatted_value':'42 L/h'},
                               'context':{'period_label':'YTD'},'statistics':{'median':40}}
        result=unified_analysis('Fuel median YTD',user=self.user)
        self.assertEqual(result['answer_status'],'ANSWERABLE')
        self.assertTrue(result['tables'])
        self.assertEqual(result['payloads'][0]['statistics']['median'],40)

    @patch('codex_chatbot.tools.unified.resolve_minesite_from_question',return_value=None)
    @patch('codex_chatbot.tools.unified.extract_intent',return_value={'filters':{'period':'ytd'}})
    @patch('codex_chatbot.tools.unified.performance_payload')
    def test_missing_detail_is_partial_not_invented(self,provider,extract,resolve):
        provider.return_value={'metric':{'raw_value':42,'formatted_value':'42 h'},'context':{'period_label':'YTD'}}
        result=unified_analysis('MTBF target YTD',user=self.user)
        self.assertEqual(result['answer_status'],'PARTIALLY_ANSWERABLE')
        self.assertIn('MTBF: target',result['unavailable_sections'])

    def test_metric_required_for_unqualified_statistics(self):
        result=unified_analysis('Donne la médiane de Fekola',user=self.user)
        self.assertEqual(result['answer_status'],'NEEDS_CLARIFICATION')
