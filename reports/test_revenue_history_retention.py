from contextlib import nullcontext
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from . import revenue_history_retention as retention
from .models import MappingAuditLog, MappingSynchronizationRun, RevenueSourceSnapshot

NOW = datetime(2026, 11, 15, 1, 0, tzinfo=dt_timezone.utc)


class RevenueHistoryRetentionTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.config = self.settings(REVENUE_HISTORY_RETENTION_DIRECTORY=self.temp.name)
        self.config.enable(); self.addCleanup(self.config.disable)
        # Disk/log operations are exercised separately; both SQLite and the
        # isolated SQL Server test database must never touch BODEFM or backups.
        headroom = patch.object(retention, '_headroom')
        headroom.start(); self.addCleanup(headroom.stop)
        retention._write('policy.json', {'enabled': True, 'backup_verified_at': NOW.isoformat(), 'backup_file': 'test-only'})
        self.old = self.run_for(10)
        self.active_run = self.run_for(20)
        self.active = self.row(self.active_run, active=True, amount='-21.37', date='2024-01-01')

    def run_for(self, days, **extra):
        return MappingSynchronizationRun.objects.create(status='Completed', completed_at=NOW-timedelta(days=days), **extra)

    def row(self, run, *, active=False, seen=None, amount='10.00', date='2025-01-01'):
        return RevenueSourceSnapshot.objects.create(synchronization_run=run, source_record_id=str(RevenueSourceSnapshot.objects.count()),
            source_last_seen_at=seen or run.completed_at, source_hash='test', active=active, revenue_eur=Decimal(amount),
            revenue_ytd_eur=Decimal(amount), division='MI', lob='PARTS', business_date=date, period_year=2025)

    def apply(self, **kwargs):
        return retention.run_pass(now=NOW, **kwargs)

    def test_only_expired_inactive_import_copies_are_deleted(self):
        expired = self.row(self.old)
        recent = self.row(self.run_for(2))
        result = self.apply()
        self.assertEqual(result['status'], 'Completed')
        self.assertEqual(result['deleted_rows'], 1)
        self.assertFalse(RevenueSourceSnapshot.objects.filter(pk=expired.pk).exists())
        self.assertTrue(RevenueSourceSnapshot.objects.filter(pk=recent.pk).exists())
        self.active.refresh_from_db()
        self.assertEqual(self.active.revenue_eur, Decimal('-21.37'))
        self.assertEqual(self.active.business_date.isoformat(), '2024-01-01')
        self.assertTrue(result['active_financials_unchanged'])

    def test_exact_72_hours_and_recently_seen_rows_are_preserved(self):
        boundary = self.row(self.run_for(3))
        recent_seen = self.row(self.old, seen=NOW-timedelta(days=1))
        self.assertEqual(self.apply()['deleted_rows'], 0)
        self.assertEqual(RevenueSourceSnapshot.objects.filter(pk__in=[boundary.pk, recent_seen.pk]).count(), 2)

    def test_any_active_row_protects_the_entire_import_version(self):
        inactive_same_run = self.row(self.active_run)
        self.apply()
        self.assertTrue(RevenueSourceSnapshot.objects.filter(pk=inactive_same_run.pk).exists())

    def test_hold_flag_and_review_references_protect_old_versions(self):
        held = self.row(self.run_for(10, source_context_json={'revenue_retention_hold': 'audit in progress'}))
        reviewed = self.row(self.old)
        with patch.object(retention.BusinessReviewSnapshot.objects, 'order_by') as query:
            query.return_value.values_list.return_value = [self.old.pk]
            self.assertEqual(self.apply()['deleted_rows'], 0)
        self.assertEqual(RevenueSourceSnapshot.objects.filter(pk__in=[held.pk, reviewed.pk]).count(), 2)

    def test_failed_unknown_date_and_other_source_versions_survive(self):
        failed = self.run_for(10); failed.status = 'Failed'; failed.save()
        undated = MappingSynchronizationRun.objects.create(status='Completed')
        other = self.run_for(10, source='Another source')
        for run in (failed, undated, other): self.row(run, seen=NOW-timedelta(days=10))
        self.assertEqual(self.apply()['deleted_rows'], 0)

    def test_headers_and_audit_records_are_retained(self):
        self.row(self.old)
        audit = MappingAuditLog.objects.create(action='test', entity_type='MappingSynchronizationRun', entity_id=str(self.old.pk))
        self.apply()
        self.assertTrue(MappingSynchronizationRun.objects.filter(pk=self.old.pk).exists())
        self.assertTrue(MappingAuditLog.objects.filter(pk=audit.pk).exists())

    def test_batches_are_bounded_and_the_next_pass_continues(self):
        for _ in range(5): self.row(self.old)
        first = self.apply(max_batches=1, batch_size=2)
        self.assertEqual(first['status'], 'More pending'); self.assertEqual(first['deleted_rows'], 2)
        second = self.apply(batch_size=2)
        self.assertEqual(second['deleted_rows'], 3)
        self.assertEqual(retention.status()['total_deleted_rows'], 5)

    def test_failure_after_one_commit_preserves_progress_and_can_resume(self):
        for _ in range(3): self.row(self.old)
        original = retention._delete_batch
        def interrupted(*args):
            if not RevenueSourceSnapshot.objects.filter(synchronization_run=self.old).count() == 3:
                raise RuntimeError('provider secret must not persist')
            return original(*args)
        with patch.object(retention, '_delete_batch', side_effect=interrupted):
            first = self.apply(batch_size=1)
        self.assertEqual(first['status'], 'Paused'); self.assertEqual(first['deleted_rows'], 1)
        self.assertNotIn('secret', (Path(self.temp.name)/'state.json').read_text())
        self.assertEqual(self.apply()['deleted_rows'], 2)
        self.assertEqual(retention.status()['total_deleted_rows'], 3)

    def test_an_import_in_progress_pauses_cleanup(self):
        self.row(self.old); MappingSynchronizationRun.objects.create(status='Running')
        self.assertEqual(self.apply()['code'], 'IMPORT_IN_PROGRESS')
        self.assertTrue(retention._rows(self.old.pk, NOW).exists())

    def test_backup_disk_or_dependency_issue_prevents_deletion(self):
        self.row(self.old)
        for name, code in (('_headroom','BACKUP_DISK_SPACE_LOW'),('_check_dependencies','DEPENDENCY_REVIEW_REQUIRED')):
            with patch.object(retention, name, side_effect=retention.RetentionStopped(code)):
                result = self.apply()
                self.assertEqual(result['code'], code); self.assertEqual(result['deleted_rows'], 0)

    def test_disabled_unverified_or_another_worker_means_no_mutation(self):
        self.row(self.old)
        for policy in ({'enabled': False}, {'enabled': True}):
            retention._write('policy.json', policy)
            self.assertEqual(self.apply()['status'], 'Disabled')
        retention._write('policy.json', {'enabled': True, 'backup_verified_at': 'test'})
        with patch.object(retention, 'retention_lock', return_value=nullcontext(False)):
            self.assertEqual(self.apply()['status'], 'Already running')
        self.assertTrue(retention._rows(self.old.pk, NOW).exists())

    def test_native_lock_excludes_another_owner(self):
        with retention.retention_lock() as first:
            self.assertTrue(first)
            with retention.retention_lock() as second: self.assertFalse(second)

    def test_default_command_is_read_only_and_disable_is_reversible(self):
        row = self.row(self.old)
        output = StringIO(); call_command('revenue_history_retention', stdout=output)
        self.assertTrue(json.loads(output.getvalue())['enabled'])
        retention.set_enabled(False)
        self.assertFalse(retention.status()['enabled'])
        self.assertTrue(RevenueSourceSnapshot.objects.filter(pk=row.pk).exists())

    def test_unsafe_batch_limits_are_rejected(self):
        for args in ({'batch_size':1001},{'max_batches':0},{'seconds':61}):
            with self.assertRaises(ValueError): self.apply(**args)

    def test_explicit_data_rollback_pins_preserve_old_copies(self):
        row = self.row(self.old)
        policy = retention._read('policy.json'); policy['protected_run_ids'] = [str(self.old.pk)]
        retention._write('policy.json', policy)
        self.assertEqual(self.apply()['deleted_rows'], 0)
        self.assertTrue(RevenueSourceSnapshot.objects.filter(pk=row.pk).exists())

    def test_scheduler_waits_one_hour_after_completion_and_retries_backlog(self):
        with patch.object(retention, 'run_pass') as work:
            retention._write('state.json', {'status': 'Completed', 'finished_at': NOW.isoformat()})
            retention.scheduled_pass(NOW+timedelta(minutes=59)); work.assert_not_called()
            retention.scheduled_pass(NOW+timedelta(hours=1)); work.assert_called_once()
            work.reset_mock()
            retention._write('state.json', {'status': 'More pending', 'finished_at': NOW.isoformat()})
            retention.scheduled_pass(NOW+timedelta(minutes=1)); work.assert_called_once()

    def test_scheduler_does_not_query_when_policy_disabled(self):
        retention._write('policy.json', {'enabled': False})
        with patch.object(retention, 'run_pass') as work:
            retention.scheduled_pass(NOW); work.assert_not_called()

    def test_paused_pass_does_not_inherit_a_previous_financial_success(self):
        self.row(self.old)
        retention._write('state.json', {'active_financials_unchanged': True, 'finished_at': NOW.isoformat(), 'seconds': 4})
        with patch.object(retention, '_headroom', side_effect=retention.RetentionStopped('LOG_REUSE_BLOCKED')):
            result = self.apply()
        self.assertEqual(result['status'], 'Paused')
        self.assertIsNone(result['active_financials_unchanged'])

    def test_session_restore_failure_is_persisted_instead_of_leaving_running(self):
        with patch.object(retention, '_restore_lock_timeout', return_value=False): result = self.apply()
        self.assertEqual(result['status'], 'Paused')
        self.assertEqual(retention.status()['code'], 'CONNECTION_RESET')

    def test_daily_worker_default_is_five_small_batches(self):
        for _ in range(6): self.row(self.old)
        result = self.apply(batch_size=1)
        self.assertEqual(result['deleted_rows'], 5)
        self.assertEqual(result['status'], 'More pending')
