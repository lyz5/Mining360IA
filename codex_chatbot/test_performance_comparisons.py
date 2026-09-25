from datetime import date
from unittest.mock import patch
from django.test import SimpleTestCase, TestCase
from django.contrib.auth import get_user_model
from .tools.performance_request import parse_request, monthly_windows
from .tools.unified import unified_analysis


class PerformanceRequestTests(SimpleTestCase):
    def test_date_windows(self):
        examples={
            'MTBF janvier 2025':'custom:2025-01-01:2025-01-31',
            'MTTR en 2024':'custom:2024-01-01:2024-12-31',
            'MTBS du 2026-02-03 au 2026-03-15':'custom:2026-02-03:2026-03-15',
            'MTBF du 03/02/2026 au 15/03/2026':'custom:2026-02-03:2026-03-15',
            'MTBF de janvier à mars 2026':'custom:2026-01-01:2026-03-31',
            'MTBF MTD':'custom:2026-09-01:2026-09-21',
            'MTBF last year':'custom:2025-01-01:2025-12-31',
            'MTBF 12 derniers mois':'last_12_months',
            'MTBF YTD':'ytd',
        }
        for question,period in examples.items():
            with self.subTest(question=question):
                self.assertEqual(parse_request(question,{},date(2026,9,21))[0]['period'],period)

    def test_groupings_and_scope(self):
        for phrase,dimension in [('par site','minesite'),('by model','model'),('par famille','family')]:
            params,_=parse_request('MTBF '+phrase+' YTD',{'minesite':'Fekola','model':'777'})
            self.assertEqual(params['breakdown'],dimension)
            self.assertEqual(params['minesite'],'Fekola')
            self.assertEqual(params['model'],'777')

    def test_invalid_dates_and_ambiguous_periods_do_not_default_to_ytd(self):
        for question in ['MTBF du 2026-03-01 au 2026-02-01','MTBF 2026-02-30 to 2026-03-01',
                         'MTBF YTD 2025','MTBF 2024 et 2025']:
            with self.subTest(question=question),self.assertRaises(ValueError):
                parse_request(question,{},date(2026,9,21))

    def test_month_windows_keep_partial_boundaries(self):
        self.assertEqual(monthly_windows('custom:2024-02-15:2024-03-05',date(2026,9,21)),
                         ['custom:2024-02-15:2024-02-29','custom:2024-03-01:2024-03-05'])

    def test_named_family_is_not_silently_ignored(self):
        params,_=parse_request('MTTR famille OFF-HIGHWAY TRUCK en août 2026',{})
        self.assertEqual(params['family'],'OFF-HIGHWAY TRUCK')
        self.assertEqual(params['period'],'custom:2026-08-01:2026-08-31')


class ComparisonRoutingTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_user('comparison-reader',is_superuser=True)

    @patch('codex_chatbot.tools.unified.resolve_minesite_from_question',return_value=None)
    @patch('codex_chatbot.tools.unified.extract_intent',return_value={'filters':{'minesite':'Fekola'}})
    @patch('codex_chatbot.tools.unified.performance_payload')
    def test_monthly_model_rows_use_semantic_values_without_averaging(self,provider,extract,resolve):
        provider.side_effect=lambda user,params: {'context':{'period_label':params['period'],'period_code':params['period'],'breakdown':'model'},
            'breakdown':[{'entity':'777','metric_value':12.345,'formatted_value':'12.35 h'}]}
        result=unified_analysis('MTBF Fekola par modèle par mois de janvier à mars 2026',user=self.user)
        self.assertEqual(result['answer_status'],'ANSWERABLE')
        self.assertEqual(len(result['rows']),3)
        self.assertEqual([r['value'] for r in result['rows']],[12.345]*3)
        self.assertEqual(provider.call_args.args[1]['minesite'],'Fekola')
        self.assertEqual(provider.call_args.args[1]['breakdown'],'model')

    @patch('codex_chatbot.tools.unified.resolve_minesite_from_question',return_value=None)
    @patch('codex_chatbot.tools.unified.extract_intent',return_value={'filters':{}})
    @patch('codex_chatbot.tools.unified.performance_payload',return_value={'context':{'breakdown':'overall'},'metric':{'raw_value':1}})
    def test_wrong_central_grouping_is_rejected(self,provider,extract,resolve):
        result=unified_analysis('MTBF par famille YTD',user=self.user)
        self.assertEqual(result['answer_status'],'TEMPORARILY_UNAVAILABLE')
