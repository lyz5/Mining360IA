from unittest.mock import patch
from django.test import TestCase
from .homepage_availability_service import HomepageAvailabilityService, HomepageAvailabilityError
from .homepage_fuel_service import HomepageFuelService
from .test_homepage_availability_command_center import HomepageAvailabilityCommandCenterTests, SAMPLE_ROWS


class ExtendedPerformanceServiceTests(TestCase):
    setUp = HomepageAvailabilityCommandCenterTests.setUp

    @patch('reports.homepage_availability_service.get_dax_template',return_value=None)
    def test_custom_dates_and_family_are_applied_to_official_measure(self,template):
        service=HomepageAvailabilityService(self.user)
        request=service.request_from_params({'metric':'mtbf','period':'custom:2024-02-01:2024-02-29','breakdown':'family','minesite':'Fekola'})
        dax=service.build_dax(request,{'minesite':['Fekola']})
        self.assertIn('VAR __StartDate = DATE(2024, 2, 1)',dax)
        self.assertIn('VAR __LatestDate = DATE(2024, 2, 29)',dax)
        self.assertIn('[MTBF Per Equip]',dax)
        self.assertIn('[ParentProductGroup]',dax)
        self.assertIn('TREATAS({"Fekola"}',dax)

    def test_cache_isolates_dates_and_grouping(self):
        service=HomepageAvailabilityService(self.user)
        requests=[service.request_from_params({'period':period,'breakdown':dimension})
                  for period in ['custom:2025-01-01:2025-01-31','custom:2026-01-01:2026-01-31']
                  for dimension in ['model','family']]
        self.assertEqual(len({service._cache_key(request,{},'') for request in requests}),4)

    def test_invalid_range_rejected_before_query(self):
        service=HomepageAvailabilityService(self.user)
        with self.assertRaises(HomepageAvailabilityError):
            service.request_from_params({'period':'custom:2026-03-01:2026-02-01'})

    def test_new_grouping_does_not_expand_authorized_scope(self):
        service=HomepageAvailabilityService(self.user)
        request=service.request_from_params({'metric':'mttr','breakdown':'family','minesite':'Fekola',
                                            'period':'custom:2026-08-01:2026-08-31'})
        with self.assertRaises(HomepageAvailabilityError) as caught:
            service._merge_filters({'minesite':['Essakane']},request.filters)
        self.assertEqual(caught.exception.status,403)

    def test_fuel_custom_family_uses_official_measure_and_exact_dates(self):
        service=HomepageFuelService(self.user)
        request=service.request_from_params({'period':'custom:2026-08-01:2026-08-31','breakdown':'family','minesite':'Fekola','family':'OFF-HIGHWAY TRUCK'})
        self.assertEqual(request.filters['minesite'],'B2Gold Fekola')
        dax=service.build_dax(request,request.filters,{})
        self.assertIn('VAR __LatestDate = DATE(2026, 8, 31)',dax)
        self.assertIn('"GroupLPH", [Mean LPH]',dax)
        self.assertIn('[ParentProductGroup]',dax)
        self.assertIn('"RowType", "trend"',dax)
        self.assertIn('TREATAS({"OFF-HIGHWAY TRUCK"}',dax)

    def test_fuel_unsupported_filter_cannot_be_silently_ignored(self):
        service=HomepageFuelService(self.user)
        with self.assertRaises(HomepageAvailabilityError):
            service.request_from_params({'customer':'secret-scope'})

    def test_fuel_scope_restriction_survives_new_grouping(self):
        service=HomepageFuelService(self.user)
        request=service.request_from_params({'breakdown':'family','minesite':'Fekola'})
        with self.assertRaises(HomepageAvailabilityError) as caught:
            service._merge_filters({'minesite':['IAMGOLD Essakane']},request.filters)
        self.assertEqual(caught.exception.status,403)
