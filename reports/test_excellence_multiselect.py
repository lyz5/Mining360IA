from types import SimpleNamespace
from unittest.mock import patch
from django.http import QueryDict
from django.test import SimpleTestCase, RequestFactory
from .excellence_filter_values import read_filters, merge_authorized_filters, option_filters
from .homepage_availability_service import HomepageAvailabilityService, HomepageAvailabilityError
from .homepage_fuel_service import HomepageFuelService
from .homepage_connectivity_service import HomepageConnectivityService


class ExcellenceMultiSelectTests(SimpleTestCase):
    def test_repeated_values_are_not_split_on_punctuation_or_lost(self):
        params = QueryDict('minesite=Site+A&minesite=Site+B&model=777&model=789&equipment=Unit%2C1')
        result = read_filters(params, ('minesite', 'model', 'equipment'))
        self.assertEqual(result, {'minesite': ['Site A','Site B'], 'model':['777','789'], 'equipment':'Unit,1'})
        self.assertEqual(read_filters({'model': ['789','789','']}, ['model']), {'model':'789'})

    def services(self):
        for cls in (HomepageAvailabilityService, HomepageFuelService, HomepageConnectivityService):
            service = cls.__new__(cls)
            service.config = SimpleNamespace(default_period='ytd',default_breakdown='overall',equipment_page_size=25)
            service.filter_mappings = {}
            yield service

    def test_all_three_services_preserve_multi_filters(self):
        params = QueryDict('minesite=SNIM-Guelb&minesite=Fekola&model=777&model=789&equipment=A&equipment=B')
        for service in self.services():
            request = service.request_from_params(params)
            self.assertEqual(len(request.filters['minesite']), 2)
            self.assertEqual(request.filters['model'], ['777','789'])
            self.assertEqual(request.filters['equipment'], ['A','B'])
        fuel = HomepageFuelService.__new__(HomepageFuelService)
        self.assertEqual(fuel.request_from_params(params).filters['minesite'], ['SNIM-Guelb','B2Gold Fekola'])

    def test_every_selected_site_must_be_authorized_for_every_service(self):
        for service in self.services():
            with self.assertRaises(HomepageAvailabilityError) as error:
                service._merge_filters({'minesite':['SNIM-Guelb']}, {'minesite':['SNIM-Guelb','Forbidden']})
            self.assertEqual(error.exception.status,403)
            self.assertEqual(service._merge_filters({'minesite':['SNIM-Guelb','Fekola']}, {'minesite':['snim-guelb','fekola']})['minesite'], ['SNIM-Guelb','Fekola'])

    def test_clearing_filters_preserves_restricted_scope(self):
        self.assertEqual(merge_authorized_filters({'minesite':['A']}, {'minesite':[]}), {'minesite':['A']})

    def test_dropdowns_restore_authorization_but_release_requested_children(self):
        scope = {'minesite':['A','B'], 'customer':['Restricted']}
        merged = {'minesite':['A'], 'customer':['Restricted'], 'model':['789'], 'equipment':['Truck1']}
        self.assertEqual(option_filters(merged, scope, 'minesite'), scope)
        self.assertEqual(option_filters(merged, scope, 'model'), {'minesite':['A'], 'customer':['Restricted']})
        self.assertEqual(option_filters(merged, scope, 'equipment')['model'], ['789'])

    def test_dax_uses_sets_and_existing_official_measures(self):
        service = HomepageConnectivityService.__new__(HomepageConnectivityService)
        request = service.request_from_params({'minesite':['A','B'],'model':['777','789']})
        merged = service._merge_filters({'minesite':['A','B']}, request.filters)
        dax = service.build_dax(request, merged, {'minesite':['A','B']})
        self.assertIn('TREATAS({"A", "B"}',dax)
        self.assertIn('TREATAS({"777", "789"}',dax)
        self.assertIn('[% Connected _]',dax)
        self.assertEqual(dax.count('[Focus]'),6)
        self.assertNotIn('DATESBETWEEN',dax)

    def test_api_keeps_repeated_values(self):
        from .homepage_views import availability_command_center_api
        request = RequestFactory().get('/api/home/availability-command-center/?metric=availability&minesite=A&minesite=B')
        request.user = SimpleNamespace(is_authenticated=True)
        with patch('reports.homepage_views._available',return_value=True), patch('reports.homepage_views._authorized',return_value=True), patch('reports.homepage_views.label_completed_ytd',side_effect=lambda payload,*args:payload), patch('reports.dashboard_snapshots.excellence_snapshot',return_value={'ok':True}) as snapshot:
            response = availability_command_center_api(request)
        self.assertEqual(response.status_code,200)
        self.assertEqual(snapshot.call_args.args[1].getlist('minesite'),['A','B'])

    def test_unsupported_remote_multi_selection_is_not_silently_narrowed(self):
        from .dashboard_snapshots import excellence_snapshot
        with patch('reports.dashboard_snapshots.configuration',return_value={'role':'replica'}), patch('reports.dashboard_snapshot_client.remote_snapshot') as remote:
            with self.assertRaises(HomepageAvailabilityError):
                excellence_snapshot(object(), QueryDict('minesite=A&minesite=B'))
            remote.assert_not_called()
