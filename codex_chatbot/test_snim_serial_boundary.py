from django.test import SimpleTestCase
from reports.machine_performance_intent_service import detect_machine_performance_intent, enrich_machine_performance_intent


class SnimSerialBoundaryTests(SimpleTestCase):
    def test_snim_is_not_a_serial_prefix(self):
        for question in [
            'Donne moi dispo en YTD de SNIM-guelb sur les 789?',
            'Dispo SNIM-Guelb 789 YTD', 'Fuel SNIM-Guelb 789',
            'LPH SNIM-Guelb', 'SNIM Guelb 789',
        ]:
            self.assertNotEqual(detect_machine_performance_intent(question), 'lookup_equipment_by_serial')
            result = enrich_machine_performance_intent({'filters': {'model': '789'}}, question)
            self.assertNotIn('serial_number', result['filters'])
            self.assertEqual(result['filters']['model'], '789')

    def test_explicit_serial_prefixes_still_work(self):
        for prefix in ['SN', 'S/N', 'Serial number', 'Numéro de série']:
            result = enrich_machine_performance_intent({'filters': {}}, f'{prefix}: XDT02044')
            self.assertEqual(result['filters']['serial_number'].upper(), 'XDT02044')

    def test_kpi_serial_filter_is_preserved(self):
        result = enrich_machine_performance_intent({'filters': {'serial_number': 'XDT02044'}},
                                                  'Availability SN XDT02044 YTD')
        self.assertEqual(result['filters']['serial_number'], 'XDT02044')
