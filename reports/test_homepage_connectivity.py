from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from .homepage_connectivity_service import HomepageConnectivityService
from .homepage_availability_service import HomepageAvailabilityError


class ConnectivityTests(SimpleTestCase):
    def setUp(self):
        self.service = HomepageConnectivityService.__new__(HomepageConnectivityService)
        self.service.report = SimpleNamespace(default_rls_role='Global')
        self.service.user = SimpleNamespace(is_authenticated=True, email='test@example.invalid',
            platformuser=SimpleNamespace(business_performance_scope={'minesite':['SNIM-Guelb']},
                user_principal_name='test@example.invalid'), get_username=lambda:'test')

    def test_old_period_links_always_resolve_to_current_state(self):
        for period in ('ytd', 'last_12_months', 'custom:2026-01-01:2026-08-31', 'current'):
            request = self.service.request_from_params({'period': period})
            self.assertEqual(request.period, 'current')
            query = self.service.build_dax(request, {}, {})
            self.assertNotIn('DATESBETWEEN', query)
            self.assertNotIn("'Date'", query)

    def test_scope_is_enforced_in_summary_groups_and_options(self):
        with patch('reports.homepage_connectivity_service.is_platform_admin',return_value=False):
            scope,role,identity=self.service._scope()
        request=self.service.request_from_params({'period':'custom:2026-01-01:2026-08-31'})
        query=self.service.build_dax(request,scope,scope)
        self.assertEqual(query.count('TREATAS({"SNIM-Guelb"}'),6)
        self.assertIn('[% Connected _]',query)
        self.assertIn('[% Reporting_]',query)
        self.assertEqual(query.count('TREATAS({"Yes"}, \'MineSiteList_MiningProd\'[Focus])'),6)
        self.assertNotIn('DATE(',query)
        with self.assertRaises(HomepageAvailabilityError):
            self.service._merge_filters(scope,{'minesite':'Fekola'})

    def test_unknown_user_scope_is_denied(self):
        self.service.user.platformuser.business_performance_scope={}
        with patch('reports.homepage_connectivity_service.is_platform_admin',return_value=False):
            with self.assertRaises(HomepageAvailabilityError) as cm:self.service._scope()
        self.assertEqual(cm.exception.status,403)

    def test_api_does_not_resolve_a_ytd_window_for_connectivity(self):
        from django.test import RequestFactory
        from .homepage_views import availability_command_center_api
        request = RequestFactory().get('/api/home/availability-command-center/', {'metric':'connectivity','period':'ytd'})
        request.user = self.service.user
        with patch('reports.homepage_views._available', return_value=True), \
             patch('reports.homepage_views._authorized', return_value=True), \
             patch('reports.homepage_views.completed_ytd_period') as period, \
             patch('reports.dashboard_snapshots.excellence_snapshot', return_value={'ok':True}) as snapshot:
            response = availability_command_center_api(request)
        self.assertEqual(response.status_code,200)
        period.assert_not_called()
        self.assertEqual(snapshot.call_args.args[1]['period'],'current')

    def test_customer_scope_cannot_be_silently_dropped(self):
        self.service.user.platformuser.business_performance_scope['customer']=['Restricted customer']
        with patch('reports.homepage_connectivity_service.is_platform_admin',return_value=False):
            with self.assertRaises(HomepageAvailabilityError):self.service._scope()

    def test_blank_is_not_zero_and_percentages_are_not_recomputed(self):
        request=self.service.request_from_params({'period':'custom:2026-01-01:2026-08-31'})
        payload=self.service._normalize([{'[RowType]':'summary','[total_assets]':4,
            '[connected_count]':0,'[connected_ratio]':0,'[reporting_ratio]':0.42}],request,10)
        self.assertEqual(payload['connectivity']['connected_ratio'],0)
        self.assertIsNone(payload['connectivity']['reporting_count'])
        self.assertEqual(payload['connectivity']['reporting_ratio'],0.42)

    def test_empty_flow_response_is_an_error(self):
        request=self.service.request_from_params({})
        with self.assertRaises(HomepageAvailabilityError):self.service._normalize([],request,1)

    def test_missing_inspectdata5_never_falls_back(self):
        from .power_automate import get_flow_url
        with patch('reports.system_configuration_service.integration_value',return_value=''), \
             patch('reports.power_automate._local_powerbi_credentials',return_value={'POWER_AUTOMATE_DAX_FLOW_URL':'wrong-flow'}), \
             patch.dict('os.environ',{},clear=True):
            self.assertEqual(get_flow_url(self.service.DATASET_NAME),'')
