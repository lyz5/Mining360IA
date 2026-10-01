from copy import deepcopy
from unittest.mock import patch
from django.test import SimpleTestCase
from .orchestrator import _compose_with_codex
from .tools.quick_kpi import quick_kpi_answer


def evidence(code='mtbf', value='21.24 h'):
    return {'kind': 'governed_answer', 'answer_status': 'ANSWERABLE',
            'source_table': 'Excellence Center governed semantic services',
            'requested_views': [], 'rows': [{'metric': code.upper(), 'value': 21.24}],
            'payloads': [{'context': {'metric_code': code, 'breakdown': 'overall',
                                     'period_label': 'YTD — mois terminés',
                                     'start_date': '2026-01-01', 'end_date': '2026-08-31',
                                     'filters': {'minesite': 'SNIM-Guelb', 'model': '789'}},
                          'metric': {'raw_value': 21.24, 'formatted_value': value},
                          'summary': {'equipment_count': 44},
                          'data_quality': {'last_refresh_at': '2026-09-30', 'is_stale': True}}]}


class QuickKpiTests(SimpleTestCase):
    @patch('codex_chatbot.orchestrator.run_grounded_turn', side_effect=AssertionError('Unexpected AI call'))
    @patch('codex_chatbot.orchestrator._resolve_codex_cli_path', side_effect=AssertionError('Unexpected CLI lookup'))
    def test_all_five_simple_kpis_skip_codex_and_preserve_evidence(self, cli, ai):
        for code,value in [('availability','84.14%'),('mtbf','21.24 h'),('mtbs','16.54 h'),('mttr','5.43 h'),('fuel','42.1 L/h')]:
            original=evidence(code,value);before=deepcopy(original)
            answer,thread,turn=_compose_with_codex(f'Donne moi le {code} des 789 SNIM-Guelb YTD',original,'existing-thread')
            for expected in [value,'SNIM-Guelb','789','2026-08-31','44','Source','ancienne','Couverture']:
                self.assertIn(expected,answer)
            self.assertEqual((thread,turn),('existing-thread',''))
            self.assertEqual(original,before)

    def test_dedicated_availability_and_zero_are_supported(self):
        e=evidence('availability','0.00%');p=e['payloads'][0]
        p['metric']['raw_value']=0
        e={**p,'kind':'availability_summary','availability':p['metric'],'source_measure':'[Avail Per Equip]'}
        answer=quick_kpi_answer('Disponibilité SNIM-Guelb YTD',e)
        self.assertIn('0.00%',answer)
        self.assertIn('[Avail Per Equip]',answer)

    def test_explanations_and_comparisons_keep_ai(self):
        for q in ['Explique le MTBF','Pourquoi le MTTR augmente ?', 'Donne le MTBF et analyse les causes',
                  'Compare MTBF et MTBS','Le MTTR est-il normal ?', 'Donne la définition du MTBF',
                  'Show how MTBF is calculated', 'What does MTBF mean?']:
            self.assertIsNone(quick_kpi_answer(q,evidence()),q)

    def test_documents_revenue_and_grouped_or_incomplete_results_are_not_shortcut(self):
        variations=[{'kind':'revenue_summary'}, {'answer_status':'ACCESS_RESTRICTED'},
                    {'answer_status':'PARTIALLY_ANSWERABLE'}, {'document_sources':[{}]},
                    {'requested_views':['trend']}, {'unavailable_sections':['quality']},
                    {'rows':[{'dimension':'equipment'}]}]
        for change in variations:
            self.assertIsNone(quick_kpi_answer('Donne le MTBF', {**evidence(),**change}))
        for change in [{'raw_value':None},{'quality_status':'out_of_range'}]:
            e=evidence();e['payloads'][0]['metric'].update(change)
            self.assertIsNone(quick_kpi_answer('Donne le MTBF',e))

    def test_multiple_kpis_keep_each_source_scope_and_units(self):
        e=evidence();other=evidence('fuel','42 L/h')
        e['rows']+=other['rows'];e['payloads']+=other['payloads']
        answer=quick_kpi_answer('Donne MTBF et LPH',e)
        self.assertIn('21.24 h',answer);self.assertIn('42 L/h',answer)
