"""Regression coverage for the SNIM presentation's natural-language requests."""
from types import SimpleNamespace
from unittest.mock import patch
from django.test import SimpleTestCase
from .tools.metric_intent import requested_metrics
from .tools.unified import unified_analysis


class PresentationRequestTests(SimpleTestCase):
    def test_plural_availability_routes_to_governed_metric(self):
        for question in ('Disponibilités SNIM-Guelb YTD', 'Disponibilites SNIM Guelb MTD'):
            with self.subTest(question=question):
                self.assertEqual(requested_metrics(question), ['availability'])

    @patch('codex_chatbot.tools.unified.is_platform_admin', return_value=True)
    @patch('codex_chatbot.tools.unified.extract_intent', return_value={'filters': {}})
    @patch('codex_chatbot.tools.unified.resolve_minesite_from_question')
    @patch('codex_chatbot.tools.unified.performance_payload')
    def test_equipment_request_keeps_site_and_requests_full_bounded_page(self, provider, resolve, extract, admin):
        resolve.return_value = SimpleNamespace(ambiguous=False, semantic_name='SNIM-Guelb')
        provider.return_value = {
            'context': {'breakdown': 'equipment', 'period_label': 'YTD'},
            'breakdown': [{'entity': 'fixture-equipment', 'metric_value': .8, 'formatted_value': '80.00%'}],
            'breakdown_pagination': {'count': 140},
        }
        result = unified_analysis('Disponibilité SNIM-Guelb par équipement YTD', user=object())
        params = provider.call_args.args[1]
        self.assertEqual(params['minesite'], 'SNIM-Guelb')
        self.assertEqual(params['page_size'], 100)
        self.assertEqual(params['breakdown'], 'equipment')
        self.assertTrue(result['tables'][0]['truncated'])
        self.assertEqual(result['tables'][0]['total_rows'], 140)
