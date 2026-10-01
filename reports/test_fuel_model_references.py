from django.test import SimpleTestCase
from .fuel_model_references import reference_catalog, reference_for_model


class FuelModelReferenceTests(SimpleTestCase):
    def test_focus_is_retained_with_and_without_requested_filters(self):
        from .homepage_fuel_service import HomepageFuelService
        for filters in ({}, {'minesite':['SNIM-Guelb']}):
            clauses = HomepageFuelService._filter_clauses(filters)
            self.assertIn('TREATAS({"Yes"}, \'MineSiteList_MiningProd\'[Focus])', clauses)

    def test_exact_models_preserve_workbook_values(self):
        for model, values in {
            '777E': (42.3, 55.45, 68.61),
            '785D': (71.91, 93.48, 115.05),
            '789D': (95.7, 123.09, 150.47),
            '793F': (117.3, 152.96, 188.62),
        }.items():
            row = reference_for_model(model)
            self.assertEqual(tuple(row[k] for k in ('low', 'medium', 'high')), values)

    def test_only_formatting_aliases_are_allowed(self):
        self.assertEqual(reference_for_model(' CAT 789d '), reference_for_model('789D'))
        for model in ('777', '785', '789', '793', '789C', '', None):
            self.assertIsNone(reference_for_model(model))

    def test_missing_bounds_are_not_inferred(self):
        row = reference_for_model('789-04')
        self.assertIsNone(row['low'])
        self.assertEqual(row['medium'], 110.45)
        self.assertIsNone(row['high'])
        self.assertFalse(row['complete'])

    def test_catalog_has_no_invented_very_high(self):
        rows = reference_catalog()['models']
        self.assertEqual(len(rows), 13)
        for row in rows:
            self.assertNotIn('very_high', row)
            if row['complete']:
                self.assertLess(row['low'], row['medium'])
                self.assertLess(row['medium'], row['high'])
