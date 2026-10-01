from copy import deepcopy
from unittest.mock import Mock
from django.test import SimpleTestCase
from .response_language import question_language, run_language, governed_notice, governed_rows_answer
from .test_quick_kpi import evidence
from .tools.quick_kpi import quick_kpi_answer


class ResponseLanguageTests(SimpleTestCase):
    def test_question_language_overrides_metric_vocabulary(self):
        for text in ['Donne moi availability', 'Et le MTBF ?', 'la consommation en litre par heure']:
            self.assertEqual(question_language(text), 'fr')
        for text in ['Show availability', 'And the MTBF?', 'What about fuel?']:
            self.assertEqual(question_language(text), 'en')
        self.assertEqual(question_language('MTBF ?', 'fr'), 'fr')
        self.assertEqual(question_language('MTBF ?', 'en'), 'en')

    def test_short_followup_inherits_only_same_conversation(self):
        run = Mock(question='MTBF?', user_id=7, created_at='earlier')
        query = run.conversation.runs.filter.return_value.order_by.return_value.values_list.return_value
        query.__getitem__ = Mock(return_value=['LPH ?', 'Donne la disponibilité'])
        self.assertEqual(run_language(run), 'fr')
        run.conversation.runs.filter.assert_called_once_with(user_id=7, created_at__lt='earlier')

    def test_switch_language_preserves_numbers_scope_dates(self):
        data = evidence('fuel', '42.1 L/h')
        data['language'] = 'fr'
        before = deepcopy(data)
        english = quick_kpi_answer('And the LPH?', data)
        french = quick_kpi_answer('Et le LPH ?', {**data, 'language': 'en'})
        for answer in [english, french]:
            for value in ['42.1 L/h', 'SNIM-Guelb', '789', '2026-01-01', '2026-08-31']:
                self.assertIn(value, answer)
        self.assertIn('Fuel consumption', english)
        self.assertIn('completed months', english)
        self.assertNotIn('mois terminés', english)
        self.assertIn('Consommation de carburant', french)
        self.assertIn('mois terminés', french)
        self.assertEqual(data, before)

    def test_notice_language(self):
        self.assertEqual(governed_notice('Périmètre non autorisé.', 'en'), 'Unauthorized scope.')
        self.assertEqual(governed_notice('Unauthorized scope.', 'fr'), 'Périmètre non autorisé.')

    def test_downtime_uses_language_and_keeps_ten_rows_and_total(self):
        data = {'language': 'en', 'fixed_top_downtime_count': 10, 'payloads': [{
            'context': {'filters': {'minesite': 'SNIM-Guelb'}, 'start_date': '2026-01-01', 'end_date': '2026-09-30'},
            'downtime_systems': {'total_hours': 120, 'rows': [
                {'system': f'System {i}', 'hours_formatted': '10 h', 'share_formatted': '8.33%'}
                for i in range(12)]}}]}
        original = deepcopy(data)
        answer = governed_rows_answer(data)
        self.assertIn('Downtime hours', answer)
        self.assertIn('120.00 h', answer)
        self.assertEqual(answer.count('| System '), 11)  # Header + ten categories.
        self.assertNotIn('| System 10 |', answer)
        self.assertEqual(data, original)
