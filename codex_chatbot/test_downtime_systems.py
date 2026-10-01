from unittest.mock import patch
from django.test import SimpleTestCase
from reports.homepage_availability_service import HomepageAvailabilityError
from .tools.downtime_systems import parse_system_rows
from .tools.unified import unified_analysis
from .tools.excellence_evidence import requested_views


class SystemRowsTests(SimpleTestCase):
    def test_blank_categories_and_full_denominator_are_preserved(self):
        data=parse_system_rows([
            {'RowType':'total','Hours':100},
            {'RowType':'system','System':'Engine','Hours':60,'SharePercentage':60},
            {'RowType':'system','System':None,'Hours':40,'SharePercentage':40},
        ],100)
        self.assertEqual(data['rows'][1]['system'],'Non classé')
        self.assertTrue(data['rows'][1]['unclassified'])
        self.assertEqual(sum(r['share_percentage'] for r in data['rows']),100)

    def test_missing_categories_wrong_denominator_and_invalid_values_fail_closed(self):
        for rows,expected in [
            ([{'RowType':'system','System':'Engine','Hours':10,'SharePercentage':100}],10),
            ([{'RowType':'total','Hours':100},{'RowType':'system','System':'Engine','Hours':60,'SharePercentage':60}],100),
            ([{'RowType':'total','Hours':100},{'RowType':'system','System':'Engine','Hours':100,'SharePercentage':100}],200),
            ([{'RowType':'total','Hours':100},{'RowType':'system','System':'Engine','Hours':100,'SharePercentage':50}],100),
            ([{'RowType':'total','Hours':float('nan')}],100),
        ]:
            with self.subTest(rows=rows),self.assertRaises(HomepageAvailabilityError):parse_system_rows(rows,expected)

    def test_zero_downtime_does_not_invent_percentages(self):
        result=parse_system_rows([{'RowType':'total','Hours':0},{'RowType':'system','System':'Engine','Hours':0}],0)
        self.assertIsNone(result['rows'][0]['share_percentage'])

    def test_systems_and_equipment_are_separate_requests(self):
        self.assertIn('downtime_systems',requested_views('Top downtimes drivers SNIM-Guelb YTD'))
        self.assertIn('downtime_systems',requested_views('Heures d’arrêt par système SNIM-Guelb YTD'))
        self.assertNotIn('downtime_systems',requested_views('Top downtime par équipement SNIM-Guelb YTD'))

    @patch('codex_chatbot.tools.unified.is_platform_admin',return_value=True)
    @patch('codex_chatbot.tools.unified.extract_intent',return_value={'filters':{}})
    @patch('codex_chatbot.tools.unified.resolve_minesite_from_question',return_value=None)
    @patch('codex_chatbot.tools.unified.performance_payload')
    @patch('codex_chatbot.tools.unified.system_breakdown')
    def test_followup_emits_system_hours_shares_and_total(self,systems,provider,resolve,extract,admin):
        context={'metric_code':'availability','period_code':'ytd','period_label':'YTD','filters':{'minesite':'SNIM-Guelb','model':'789'}}
        provider.return_value={'context':context,'summary':{'downtime_hours':10}}
        systems.return_value=parse_system_rows([{'RowType':'total','Hours':10},{'RowType':'system','System':'Engine','Hours':10,'SharePercentage':100}],10)
        result=unified_analysis('Top downtimes drivers sur cette période',user=object(),inherited_context=context)
        params=systems.call_args.args[1]
        self.assertEqual(params['minesite'],'SNIM-Guelb')
        self.assertEqual(params['model'],'789')
        self.assertEqual(params['period'],'ytd')
        self.assertEqual(result['rows'][0]['entity'],'Engine')
        self.assertEqual(result['rows'][0]['share_percentage'],100)
        self.assertEqual(result['payloads'][0]['downtime_systems']['total_hours'],10)
        self.assertTrue(any('category' in t['title'] for t in result['tables']))
