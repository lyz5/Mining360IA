"""Clock, per-user authorization, concurrency, retry and forced-read contracts."""
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone as datetime_timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings

from . import parts_fulfillment_auto_sync as daily
from .parts_fulfillment_service import LogisticsSource, PartsFulfillmentService, FulfillmentUnavailable

UTC = datetime_timezone.utc
FIVE = datetime(2026, 11, 15, 5, 0, tzinfo=UTC)


@override_settings(PARTS_FULFILLMENT_AUTO_SYNC=True, BUSINESS_REVENUE_AUTO_SYNC_HOUR=5,
                   BUSINESS_REVENUE_AUTO_SYNC_MINUTE=0, BUSINESS_REVENUE_AUTO_SYNC_TIME_ZONE='Etc/GMT',
                   BUSINESS_REVENUE_AUTO_SYNC_RETRY_MINUTES=60)
class PartsDailyRefreshTests(SimpleTestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings = override_settings(PARTS_FULFILLMENT_AUTO_SYNC_DIRECTORY=self.temp.name)
        self.settings.enable(); self.addCleanup(self.settings.disable)
        role = patch('reports.dashboard_snapshots.configuration', return_value={'role': 'disabled'})
        role.start(); self.addCleanup(role.stop)
        self.users = [SimpleNamespace(pk=1, is_active=True), SimpleNamespace(pk=2, is_active=True)]
        self.user_model = Mock()
        self.user_model.objects.filter.return_value.select_related.side_effect = lambda *args: self.users
        model = patch.object(daily, 'get_user_model', return_value=self.user_model)
        model.start(); self.addCleanup(model.stop)
        admin = patch.object(daily, 'is_platform_admin', return_value=True)
        self.admin = admin.start(); self.addCleanup(admin.stop)
        allowed = patch('reports.parts_fulfillment_views.allowed', return_value=True)
        self.allowed = allowed.start(); self.addCleanup(allowed.stop)
        self.services = {}
        for user in self.users:
            report = SimpleNamespace(pk=10, workspace_id='test-workspace', semantic_model_id='test-model',
                                     updated_at=FIVE, configuration_version=1,
                                     authentication_mode='app_owns_data', default_rls_role='Global')
            self.services[user.pk] = Mock(source=SimpleNamespace(report=report))
        service = patch.object(daily, 'PartsFulfillmentService', side_effect=lambda user: self.services[user.pk])
        self.factory = service.start(); self.addCleanup(service.stop)

    def test_no_query_before_the_shared_five_am_boundary(self):
        self.assertFalse(daily.synchronize_if_due(FIVE - timedelta(seconds=1)))
        self.factory.assert_not_called()
        self.assertFalse((Path(self.temp.name) / 'state.json').exists())
        state = daily.synchronization_state(FIVE - timedelta(seconds=1))
        self.assertEqual(state['next_scheduled_at'], FIVE.isoformat())

    def test_five_am_force_reads_each_authorized_scope_once_per_day(self):
        self.assertTrue(daily.synchronize_if_due(FIVE))
        for service in self.services.values():
            service.summary.assert_called_once_with(force_refresh=True)
        self.assertFalse(daily.synchronize_if_due(FIVE + timedelta(hours=8)))
        state = daily.synchronization_state(FIVE + timedelta(minutes=1))
        self.assertEqual(state['status'], 'Completed')
        self.assertEqual(state['completed'], 2)
        self.assertFalse(state['running'])

    def test_next_day_refreshes_again_and_late_start_catches_up(self):
        daily.synchronize_if_due(FIVE + timedelta(hours=2))
        self.assertTrue(daily.synchronize_if_due(FIVE + timedelta(days=1)))
        self.assertEqual(self.services[1].summary.call_count, 2)

    @override_settings(BUSINESS_REVENUE_AUTO_SYNC_TIME_ZONE='Asia/Tokyo')
    def test_clock_is_the_configured_revenue_clock_not_server_wall_time(self):
        before = datetime(2026, 11, 14, 19, 59, tzinfo=UTC)
        at_five = datetime(2026, 11, 14, 20, 0, tzinfo=UTC)
        self.assertFalse(daily.synchronize_if_due(before))
        self.assertTrue(daily.synchronize_if_due(at_five))

    @override_settings(BUSINESS_REVENUE_AUTO_SYNC_MINUTE=20)
    def test_minute_configuration_is_shared(self):
        self.assertFalse(daily.synchronize_if_due(FIVE))
        self.assertTrue(daily.synchronize_if_due(FIVE + timedelta(minutes=20)))

    def test_restricted_or_unauthorized_users_are_never_used_to_query(self):
        self.admin.side_effect = lambda user: user.pk == 1
        self.allowed.return_value = False
        daily.synchronize_if_due(FIVE)
        self.factory.assert_not_called()
        state = daily.synchronization_state(FIVE)
        self.assertEqual(state['status'], 'No eligible accounts')
        self.assertIsNone(state['last_success_at'])

    def test_failure_retries_only_unfinished_scope_after_backoff(self):
        self.services[2].summary.side_effect = FulfillmentUnavailable('private provider body', 'SOURCE_QUERY_FAILED')
        daily.synchronize_if_due(FIVE)
        self.assertFalse(daily.synchronize_if_due(FIVE + timedelta(minutes=59)))
        self.services[2].summary.side_effect = None
        self.assertTrue(daily.synchronize_if_due(FIVE + timedelta(hours=1)))
        self.services[1].summary.assert_called_once_with(force_refresh=True)
        self.assertEqual(self.services[2].summary.call_count, 2)
        self.assertNotIn('private provider body', (Path(self.temp.name) / 'state.json').read_text())

    def test_success_metadata_survives_a_failed_later_day(self):
        daily.synchronize_if_due(FIVE)
        previous = daily._read()['last_success_at']
        self.services[1].summary.side_effect = RuntimeError('sensitive upstream URL')
        daily.synchronize_if_due(FIVE + timedelta(days=1))
        state = daily._read()
        self.assertEqual(state['last_success_at'], previous)
        self.assertEqual(state['completed_slot'], FIVE.isoformat())
        self.assertEqual(state['status'], 'Failed')
        self.assertNotIn('sensitive', (Path(self.temp.name) / 'state.json').read_text())

    @override_settings(PARTS_FULFILLMENT_AUTO_SYNC=False)
    def test_disabled_means_no_query_or_state_write(self):
        self.assertFalse(daily.synchronize_if_due(FIVE))
        self.factory.assert_not_called()
        self.assertFalse((Path(self.temp.name) / 'state.json').exists())

    def test_replica_or_retired_origin_is_not_a_second_producer(self):
        for role in ('origin', 'replica'):
            with patch('reports.dashboard_snapshots.configuration', return_value={'role': role}):
                self.assertFalse(daily.synchronize_if_due(FIVE))
        self.factory.assert_not_called()

    def test_a_second_scheduler_cannot_query_while_the_lock_is_held(self):
        with patch.object(daily, 'scheduler_lock', return_value=nullcontext(False)):
            self.assertFalse(daily.synchronize_if_due(FIVE))
        self.factory.assert_not_called()

    def test_native_file_lock_excludes_a_second_owner(self):
        with daily.scheduler_lock() as first:
            self.assertTrue(first)
            with daily.scheduler_lock() as second:
                self.assertFalse(second)

    def test_background_thread_starts_once_without_waiting_for_revenue(self):
        previous = daily._thread
        self.addCleanup(setattr, daily, '_thread', previous)
        daily._thread = None
        with patch.object(daily.threading, 'Thread') as thread:
            thread.return_value.is_alive.return_value = True
            daily.start_parts_scheduler()
            daily.start_parts_scheduler()
        thread.assert_called_once()
        self.assertEqual(thread.call_args.kwargs['name'], 'parts-fulfillment-auto-sync')
        self.assertTrue(thread.call_args.kwargs['daemon'])
        thread.return_value.start.assert_called_once()

    def test_invalid_state_file_recovers_without_inventing_a_success(self):
        (Path(self.temp.name) / 'state.json').write_text('invalid JSON')
        self.assertIsNone(daily.synchronization_state(FIVE)['last_success_at'])
        self.assertTrue(daily.synchronize_if_due(FIVE))

    def test_browser_token_and_clock_are_private_to_the_authorized_scope(self):
        user = self.users[0]
        source = self.services[user.pk].source
        before = daily.state_for_source(user, source, FIVE - timedelta(seconds=1))
        self.assertEqual(before['next_check_at'], FIVE.isoformat())
        self.assertEqual(before['version'], '')
        daily.synchronize_if_due(FIVE)
        state = daily.state_for_source(user, source, FIVE + timedelta(minutes=1))
        self.assertTrue(state['version'])
        self.assertEqual(state['next_check_at'], (FIVE + timedelta(days=1)).isoformat())
        self.assertEqual(set(state), {'enabled', 'server_time', 'next_check_at', 'version'})
        source.report.configuration_version = 2
        self.assertEqual(daily.state_for_source(user, source, FIVE)['version'], '')

    def test_browser_waits_for_retry_without_repeated_source_queries(self):
        self.services[1].summary.side_effect = FulfillmentUnavailable('unavailable')
        daily.synchronize_if_due(FIVE)
        state = daily.state_for_source(self.users[0], self.services[1].source, FIVE + timedelta(minutes=1))
        self.assertEqual(state['next_check_at'], (FIVE + timedelta(hours=1)).isoformat())
        self.services[1].summary.assert_called_once()

    def test_summary_captures_completion_token_before_reading_cached_values(self):
        from django.test import RequestFactory
        from . import parts_fulfillment_views as views
        user = self.users[0]
        user.is_authenticated = True
        request = RequestFactory().get('/summary/', {'month': '2026-10'})
        request.user = user
        order = []
        def token(*args):
            order.append('token'); return {'enabled': True, 'version': 'before'}
        def result(*args):
            order.append('summary'); return {'kpis': {'sales': '20'}}
        with patch.object(views, 'PartsFulfillmentService', return_value=self.services[1]), \
             patch.object(views, 'state_for_source', side_effect=token):
            self.services[1].summary.side_effect = result
            response = views.summary(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(order, ['token', 'summary'])
        self.assertIn('private, no-store', response['Cache-Control'])

    def test_status_endpoint_denies_access_before_reading_metadata(self):
        from django.test import RequestFactory
        from . import parts_fulfillment_views as views
        self.users[0].is_authenticated = True
        request = RequestFactory().get('/sync-status/')
        request.user = self.users[0]
        with patch.object(views, 'allowed', return_value=False), patch.object(views, 'state_for_user') as read:
            self.assertEqual(views.sync_status(request).status_code, 403)
            read.assert_not_called()


class PartsDailyEligibilityTests(TestCase):
    def test_real_user_permissions_limit_scheduled_candidates(self):
        from django.contrib.auth import get_user_model
        from .test_business_command_center import FEATURES
        User = get_user_model()
        first = User.objects.create_superuser('daily-first', 'first@example.test', 'test-only')
        second = User.objects.create_superuser('daily-second', 'second@example.test', 'test-only')
        User.objects.create_user('daily-ordinary', password='test-only')
        User.objects.create_superuser('daily-inactive', 'inactive@example.test', 'test-only', is_active=False)
        report = SimpleNamespace(pk=10, workspace_id='test-workspace', semantic_model_id='test-model',
                                 updated_at=FIVE, configuration_version=1,
                                 authentication_mode='app_owns_data', default_rls_role='Global')
        with TemporaryDirectory() as temp, override_settings(**FEATURES, PARTS_FULFILLMENT_AUTO_SYNC=True,
             BUSINESS_REVENUE_AUTO_SYNC_HOUR=5, BUSINESS_REVENUE_AUTO_SYNC_MINUTE=0,
             BUSINESS_REVENUE_AUTO_SYNC_TIME_ZONE='Etc/GMT', PARTS_FULFILLMENT_AUTO_SYNC_DIRECTORY=temp), \
             patch('reports.dashboard_snapshots.configuration', return_value={'role': 'disabled'}), \
             patch.object(daily, 'PartsFulfillmentService') as service:
            service.return_value.source.report = report
            self.assertTrue(daily.synchronize_if_due(FIVE))
            self.assertEqual({call.args[0].pk for call in service.call_args_list}, {first.pk, second.pk})
            self.assertEqual(service.return_value.summary.call_count, 2)


class PartsForcedReadTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.source = LogisticsSource.__new__(LogisticsSource)
        self.source.user = SimpleNamespace(pk=123)
        self.source.report = SimpleNamespace(pk=5, semantic_model_id='test-model', updated_at=FIVE,
            configuration_version=1, authentication_mode='app_owns_data', default_rls_role='Global')
        self.source.refresh_id = 'test-refresh'
        self.source.query = Mock(return_value=[{'amount': '10.00001'}])
        for name in ('authorized_account_codes', 'authorized_minesite_names'):
            scope = patch('reports.parts_fulfillment_service.' + name, return_value=None)
            scope.start(); self.addCleanup(scope.stop)
        self.addCleanup(cache.clear)

    def test_scheduled_force_bypasses_only_its_scoped_query_cache(self):
        self.assertEqual(self.source.cached_query('test-dax'), [{'amount': '10.00001'}])
        self.source.query.return_value = [{'amount': '-2.000001'}]
        self.assertEqual(self.source.cached_query('test-dax'), [{'amount': '10.00001'}])
        self.assertEqual(self.source.cached_query('test-dax', force=True), [{'amount': '-2.000001'}])
        self.assertEqual(self.source.query.call_count, 2)
        self.assertEqual(self.source.cached_query('test-dax'), [{'amount': '-2.000001'}])

    def test_failure_does_not_erase_a_valid_cached_result_or_keep_lock(self):
        self.source.cached_query('test-dax')
        self.source.query.side_effect = FulfillmentUnavailable('unavailable')
        with self.assertRaises(FulfillmentUnavailable):
            self.source.cached_query('test-dax', force=True)
        self.assertEqual(self.source.cached_query('test-dax'), [{'amount': '10.00001'}])
        self.source.query.side_effect = None
        self.source.cached_query('test-dax', force=True)

    def test_different_users_keep_separate_query_caches(self):
        self.source.cached_query('test-dax')
        self.source.user = SimpleNamespace(pk=456)
        self.source.cached_query('test-dax')
        self.assertEqual(self.source.query.call_count, 2)

    def test_source_access_still_rejects_restricted_identities(self):
        with patch('reports.parts_fulfillment_service.report_for', return_value=self.source.report), \
             patch('reports.parts_fulfillment_service.is_platform_admin', return_value=False), \
             patch.object(LogisticsSource, 'refresh_state') as history:
            with self.assertRaises(FulfillmentUnavailable) as exc:
                LogisticsSource(SimpleNamespace(pk=456))
            self.assertEqual(exc.exception.code, 'SCOPED_QUERY_NOT_CONFIGURED')
            history.assert_not_called()

    def test_status_rechecks_authorization_without_any_power_bi_call(self):
        self.source.report.requires_user_identity = False
        with patch('reports.parts_fulfillment_service.report_for', return_value=self.source.report), \
             patch('reports.parts_fulfillment_service.is_platform_admin', return_value=True), \
             patch.object(LogisticsSource, 'refresh_state') as history, \
             patch.object(LogisticsSource, 'query') as query, \
             patch.object(daily, 'state_for_source', return_value={'enabled': True}) as state:
            self.assertEqual(daily.state_for_user(self.source.user), {'enabled': True})
            self.assertEqual(state.call_args.args[1].user.pk, self.source.user.pk)
            history.assert_not_called(); query.assert_not_called()
        with patch('reports.parts_fulfillment_service.report_for', return_value=self.source.report), \
             patch('reports.parts_fulfillment_service.is_platform_admin', return_value=False):
            with self.assertRaises(FulfillmentUnavailable):
                daily.state_for_user(self.source.user)

    def test_summary_force_does_not_change_measure_values_or_cohort_rules(self):
        rows = [{'MonthStart': '2026-10-01', 'orders': '100.001', 'sales': '20', 'current': '8',
                 'last': '6', 'older': '5', 'unallocated': '1', 'future': None,
                 'difference': '0', 'coverage': '2026-10-31'}]
        source = Mock(last_refresh=None)
        source.cached_query.return_value = rows
        service = PartsFulfillmentService(SimpleNamespace(pk=1), source=source, today=FIVE.date())
        regular = service.summary('2026-10')
        forced = service.summary('2026-10', force_refresh=True)
        self.assertEqual(regular, forced)
        self.assertEqual(forced['kpis']['orders'], '100.001')
        self.assertEqual(forced['kpis']['future'], '0')
        self.assertEqual(forced['kpis']['reconciliation']['status'], 'reconciled')
        self.assertEqual(source.cached_query.call_args.kwargs, {'force': True})
