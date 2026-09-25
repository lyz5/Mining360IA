from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase,TestCase
from .tools.metric_intent import requested_metrics
from .tools.fleet_inventory import fleet_analysis_from_question
from .tools.unified import unified_analysis


class MetricRecognitionTests(SimpleTestCase):
    def test_fuel_units_in_french_and_english(self):
        for text in ['Donne le litre par heure de Fekola 777 en YTD','L/h Fekola 777',
                     'litres/heure','liters per hour','litres à l’heure','LPH','consommation horaire']:
            with self.subTest(text=text):self.assertEqual(requested_metrics(text),['fuel'])

    def test_metrics_never_fall_back_to_inventory_even_with_equipment_terms(self):
        for text in ['MTBF des équipements Fekola','Availability de la flotte Fekola',
                     'Donne le litre par heure de Fekola 777 en YTD','dispo Fekola','Fekola']:
            with self.subTest(text=text):
                self.assertIsNone(fleet_analysis_from_question(text,user=None))


class MetricRoutingTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_user('metric-reader',is_superuser=True)

    @patch('codex_chatbot.tools.unified.resolve_minesite_from_question',return_value=None)
    @patch('codex_chatbot.tools.unified.extract_intent',return_value={'filters':{'period':'ytd','model':'777','minesite':'Fekola'}})
    @patch('codex_chatbot.tools.unified.performance_payload')
    def test_exact_user_question_uses_fuel_preserving_site_model_period(self,payload,extract,resolve):
        payload.return_value={'metric':{'raw_value':42,'formatted_value':'42 L/h'},'context':{'period_label':'YTD'}}
        result=unified_analysis('Donne le litre par heure de Fekola 777 en YTD',user=self.user)
        self.assertEqual(result['kind'],'governed_answer')
        self.assertEqual(result['rows'][0]['metric'],'FUEL')
        self.assertEqual(payload.call_args.args[1],{'metric':'fuel','minesite':'Fekola','model':'777','period':'ytd','breakdown':'overall'})

    @patch('codex_chatbot.tools.unified.resolve_minesite_from_question',return_value=None)
    @patch('codex_chatbot.tools.unified.extract_intent',return_value={'filters':{}})
    @patch('codex_chatbot.tools.unified.performance_payload',return_value={'metric':{'raw_value':None,'formatted_value':None}})
    def test_missing_metric_is_not_answerable(self,payload,extract,resolve):
        result=unified_analysis('L/h Fekola 777',user=self.user)
        self.assertEqual(result['answer_status'],'PARTIALLY_ANSWERABLE')
        self.assertIsNone(result['rows'][0]['value'])

    @patch('reports.dashboard_snapshots.excellence_snapshot',return_value={'metric':{'raw_value':12}})
    @patch('reports.dashboard_snapshots.enabled',return_value=True)
    def test_central_analytical_provider_is_used(self,enabled,snapshot):
        from .tools.unified import performance_payload
        params={'metric':'mtbf','minesite':'Fekola'}
        self.assertEqual(performance_payload(self.user,params)['metric']['raw_value'],12)
        snapshot.assert_called_once_with(self.user,params)
