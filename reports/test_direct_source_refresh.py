from contextlib import contextmanager
from unittest.mock import Mock,patch
from django.test import SimpleTestCase,RequestFactory
from reports import homepage_views,business_review_views
from reports.dashboard_snapshots import excellence_snapshot,business_snapshot

class DirectSourceRefreshTests(SimpleTestCase):
    def test_excellence_direct_force_reaches_source(self):
        user=Mock();service=Mock();service.get.return_value={'ok':True}
        with patch('reports.dashboard_snapshots.configuration',return_value={'role':'disabled'}), patch('reports.homepage_availability_service.HomepageAvailabilityService',return_value=service):
            result=excellence_snapshot(user,{'metric':'availability'},force=True)
        self.assertEqual(result,{'ok':True})
        service.get.assert_called_once_with(service.request_from_params.return_value,force_refresh=True)
    def test_fuel_direct_force_reaches_source(self):
        service=Mock();service.get.return_value={'ok':True}
        with patch('reports.dashboard_snapshots.configuration',return_value={'role':'disabled'}),patch('reports.homepage_fuel_service.HomepageFuelService',return_value=service):
            excellence_snapshot(Mock(),{'metric':'fuel'},force=True)
        service.get.assert_called_once_with(service.request_from_params.return_value,force_refresh=True)
    def test_business_direct_preserves_force_parameter(self):
        service=Mock();user=Mock()
        with patch('reports.dashboard_snapshots.configuration',return_value={'role':'disabled'}),patch('reports.business_command_center_service.BusinessCommandCenterService',return_value=service) as constructor:
            business_snapshot(user,{'refresh':'1'})
        constructor.assert_called_once_with(user,{'refresh':'1'})
        service.bootstrap.assert_called_once()
    def test_refresh_api_passes_force_and_checks_access(self):
        request=RequestFactory().get('/api/home/availability-command-center/',{'refresh':'1'});request.user=Mock(is_authenticated=True)
        with patch.object(homepage_views,'_available',return_value=True),patch.object(homepage_views,'_authorized',return_value=True),patch('reports.dashboard_snapshots.excellence_snapshot',return_value={'ok':True}) as source:
            self.assertEqual(homepage_views.availability_command_center_api(request).status_code,200)
            source.assert_called_once_with(request.user,request.GET,force=True)
        with patch.object(homepage_views,'_available',return_value=True),patch.object(homepage_views,'_authorized',return_value=False),patch('reports.dashboard_snapshots.excellence_snapshot') as source:
            self.assertEqual(homepage_views.availability_command_center_api(request).status_code,403);source.assert_not_called()
    def test_revenue_post_permission_and_method(self):
        request=RequestFactory().post('/sync-status/');request.user=Mock(is_authenticated=True)
        with patch.object(business_review_views,'_command_center_allowed',return_value=False),patch('reports.revenue_auto_sync.request_manual_synchronization') as sync:
            self.assertEqual(business_review_views.command_center_sync_status_api(request).status_code,403);sync.assert_not_called()
        with patch.object(business_review_views,'_command_center_allowed',return_value=True),patch('reports.revenue_auto_sync.request_manual_synchronization',return_value={'accepted':True,'run_id':'example'}) as sync:
            self.assertEqual(business_review_views.command_center_sync_status_api(request).status_code,202);sync.assert_called_once_with(request.user)
    def test_existing_revenue_run_is_reused(self):
        from reports.revenue_auto_sync import request_manual_synchronization
        @contextmanager
        def locked():yield True
        active=Mock(pk='existing')
        with patch('reports.revenue_auto_sync.scheduler_lock',locked),patch('reports.revenue_auto_sync.MappingSynchronizationRun') as model,patch('reports.revenue_auto_sync.BusinessMappingSourceSynchronizationService') as service:
            model.objects.filter.return_value.order_by.return_value.first.return_value=active
            self.assertTrue(request_manual_synchronization(Mock())['already_running']);service.assert_not_called()