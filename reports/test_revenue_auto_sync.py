from contextlib import nullcontext
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from .business_mapping_source_service import SOURCE_NAME
from .models import MappingSynchronizationRun
from .revenue_auto_sync import synchronization_state, synchronize_if_due


@override_settings(BUSINESS_REVENUE_AUTO_SYNC=True, BUSINESS_REVENUE_AUTO_SYNC_RETRY_MINUTES=60)
class RevenueAutoSyncTests(TestCase):
    def run_record(self, status='Completed', age_hours=2, through_days=1):
        run = MappingSynchronizationRun.objects.create(source=SOURCE_NAME, status=status,
            completed_at=timezone.now() - timedelta(hours=age_hours),
            source_context_json={'semantic_data_through': (timezone.localdate() - timedelta(days=through_days)).isoformat()})
        MappingSynchronizationRun.objects.filter(pk=run.pk).update(created_at=timezone.now() - timedelta(hours=age_hours))
        return run

    def test_empty_database_needs_initial_sync(self):
        self.assertTrue(synchronization_state()['due'])

    def test_fresh_yesterday_source_does_not_reload(self):
        run = self.run_record(age_hours=0)
        self.assertFalse(synchronization_state()['due'])
        self.assertEqual(synchronization_state()['source_sync_id'], str(run.pk))

    def test_source_lag_is_retried_with_backoff(self):
        run = self.run_record(through_days=4)
        self.assertTrue(synchronization_state()['due'])
        run.completed_at = timezone.now()
        run.save(update_fields=['completed_at'])
        self.assertFalse(synchronization_state()['due'])
        self.assertLess(synchronization_state()['source_through_date'], synchronization_state()['target_date'])

    def test_failure_keeps_previous_success_and_backs_off(self):
        success = self.run_record(age_hours=48, through_days=3)
        self.run_record(status='Failed', age_hours=0)
        state = synchronization_state()
        self.assertFalse(state['due'])
        self.assertTrue(state['last_attempt_failed'])
        self.assertEqual(state['source_sync_id'], str(success.pk))

    def test_running_or_queued_run_prevents_duplicates(self):
        for status in ['Running', 'Queued']:
            run = self.run_record(status=status, age_hours=0)
            self.assertFalse(synchronization_state()['due'])
            run.delete()

    @patch('reports.revenue_auto_sync.BusinessMappingSourceSynchronizationService')
    @patch('reports.revenue_auto_sync.scheduler_lock', return_value=nullcontext(True))
    def test_background_sync_uses_system_actor_without_publishing(self, lock, service):
        self.assertTrue(synchronize_if_due())
        service.assert_called_once_with(user=None)
        service.return_value.process.assert_called_once_with(service.return_value.queue.return_value)

    @patch('reports.revenue_auto_sync.BusinessMappingSourceSynchronizationService')
    @patch('reports.revenue_auto_sync.scheduler_lock', return_value=nullcontext(False))
    def test_second_scheduler_does_not_queue(self, lock, service):
        self.assertFalse(synchronize_if_due())
        service.assert_not_called()

    @patch('reports.revenue_auto_sync.BusinessMappingSourceSynchronizationService')
    @patch('reports.revenue_auto_sync.scheduler_lock', return_value=nullcontext(True))
    def test_interrupted_automatic_run_recovers_after_lock_is_released(self, lock, service):
        run = self.run_record(status='Running', age_hours=0)
        run.source_context_json = {'automatic_revenue_sync': True}
        run.save(update_fields=['source_context_json'])
        self.assertTrue(synchronize_if_due())
        run.refresh_from_db()
        self.assertEqual(run.status, 'Failed')
        self.assertEqual(run.stage_code, 'automatic_sync_interrupted')

    @override_settings(BUSINESS_REVENUE_AUTO_SYNC=False)
    @patch('reports.revenue_auto_sync.scheduler_lock')
    def test_disabled_environment_does_not_start_sync(self, lock):
        self.assertFalse(synchronize_if_due())
        lock.assert_not_called()
