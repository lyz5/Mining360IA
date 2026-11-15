"""Transactional preservation and rollback on an isolated real SQL Server DB."""
from datetime import datetime,timedelta,timezone as dt_timezone
from decimal import Decimal
from unittest import skipUnless
from unittest.mock import patch
from tempfile import TemporaryDirectory

from django.db import connection
from django.test import TestCase,TransactionTestCase

from . import revenue_history_catchup as catchup
from . import revenue_history_retention as retention
from .models import MappingSynchronizationRun,RevenueSourceSnapshot

NOW=datetime(2026,11,15,13,0,tzinfo=dt_timezone.utc)


@skipUnless(connection.vendor=='microsoft','Real SQL Server transactional test')
class RevenueHistoryCatchupTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        catchup.execute('CREATE NONCLUSTERED INDEX bo_active_revenue_cover_20261010 ON dbo.bm_revenue_source_snapshot (division,business_date) INCLUDE (active,source_account_code,lob,revenue_eur) WHERE active=1')

    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.config=self.settings(REVENUE_HISTORY_RETENTION_DIRECTORY=self.temp.name)
        self.config.enable();self.addCleanup(self.config.disable)
        self.old=self.run_for(10);self.current=self.run_for(20);self.recent=self.run_for(2);self.pinned=self.run_for(10)
        retention._write('policy.json',{'protected_run_ids':[str(self.pinned.pk)]})
        for run,count,active in ((self.old,30,False),(self.current,10,True),(self.recent,15,False),(self.pinned,5,False)):
            RevenueSourceSnapshot.objects.bulk_create([RevenueSourceSnapshot(synchronization_run=run,source_record_id=f'{run.pk}-{i}',
                source_last_seen_at=run.completed_at,active=active,source_account_name='Client été '+str(i),
                source_hash=str(i),source_account_code='000057',division='MI',lob='PARTS',business_date='2024-01-01',period_year=2024,
                revenue_eur=Decimal('-21.37') if i%2 else Decimal('123.45')) for i in range(count)])
        if RevenueSourceSnapshot._meta.get_field('revenue_eur').decimal_places==10:
            first=RevenueSourceSnapshot.objects.filter(synchronization_run=self.current).order_by('pk').first()
            catchup.execute('UPDATE dbo.bm_revenue_source_snapshot SET revenue_eur=CONVERT(decimal(28,10),%s) WHERE id=%s', [Decimal('-21.3700000001'),first.pk])

    def run_for(self,days):
        return MappingSynchronizationRun.objects.create(status='Completed',completed_at=NOW-timedelta(days=days))

    def raw_rows(self,ids=None):
        where=' WHERE synchronization_run_id IN ('+','.join("'"+value.hex+"'" for value in ids)+')' if ids else ''
        return catchup.execute('SELECT * FROM dbo.bm_revenue_source_snapshot'+where+' ORDER BY id')

    def test_only_expired_copies_removed_all_kept_columns_and_indexes_identical(self):
        keep=[self.current.pk,self.recent.pk,self.pinned.pk]
        before=self.raw_rows(keep);structure=catchup.schema()
        result=catchup.compact_versions(retention.plan(NOW))
        self.assertEqual(result['deleted_rows'],30)
        self.assertEqual(self.raw_rows(),before)
        self.assertEqual(catchup.schema(),structure)
        self.assertTrue(result['active_financials_unchanged'])
        self.assertTrue(MappingSynchronizationRun.objects.filter(pk=self.old.pk).exists())

    def test_validation_failure_rolls_back_expired_and_active_rows(self):
        before=self.raw_rows();structure=catchup.schema()
        with patch.object(catchup,'_validate_restored',side_effect=retention.RetentionStopped('TEST_VALIDATION_FAILURE')):
            with self.assertRaises(retention.RetentionStopped):catchup.compact_versions(retention.plan(NOW))
        self.assertEqual(self.raw_rows(),before)
        self.assertEqual(catchup.schema(),structure)

    def test_recently_seen_row_protects_its_entire_old_version(self):
        row=RevenueSourceSnapshot.objects.filter(synchronization_run=self.old).first()
        row.source_last_seen_at=NOW-timedelta(days=1);row.save(update_fields=['source_last_seen_at'])
        before=self.raw_rows()
        result=catchup.compact_versions(retention.plan(NOW))
        self.assertEqual(result['deleted_rows'],0);self.assertEqual(self.raw_rows(),before)

    def test_identity_values_and_next_insert_are_preserved(self):
        maximum=RevenueSourceSnapshot.objects.order_by('-pk').first().pk
        catchup.compact_versions(retention.plan(NOW))
        row=RevenueSourceSnapshot.objects.create(synchronization_run=self.recent,source_record_id='after-cleanup',source_last_seen_at=NOW)
        self.assertGreater(row.pk,maximum)

    def test_large_copy_preserves_fractional_cents_and_all_columns(self):
        import time
        started=time.monotonic()
        for run,active in ((self.old,False),(self.current,True)):
            RevenueSourceSnapshot.objects.bulk_create([RevenueSourceSnapshot(synchronization_run=run,source_record_id=f'large-{run.pk}-{i}',
                source_hash=f'{i:064x}',source_last_seen_at=run.completed_at,active=active,division='MI',lob='PARTS',
                source_account_code='000001',source_account_name='Test uniquement — client '+str(i),business_date='2024-01-01',
                period_year=2024,revenue_eur=Decimal('123.4567891000')) for i in range(10000)],batch_size=50)
        expected=self.raw_rows([self.current.pk,self.recent.pk,self.pinned.pk])
        result=catchup.compact_versions(retention.plan(NOW))
        self.assertEqual(result['deleted_rows'],10030)
        self.assertEqual(self.raw_rows(),expected)
        self.assertEqual(RevenueSourceSnapshot.objects.filter(synchronization_run=self.current).count(),10010)
        print('SQL catch-up benchmark: '+str(result['transaction_seconds'])+' seconds for '+str(result['retained_rows'])+' kept rows',flush=True)


@skipUnless(connection.vendor=='microsoft','Real SQL Server transactional test')
class RevenueHistoryReclaimSyntaxTests(TransactionTestCase):
    def test_sqlserver_2022_low_priority_shrink_syntax(self):
        self.assertTrue(connection.settings_dict['NAME'].startswith('test_'))
        catchup.execute('DBCC SHRINKFILE (1,8) WITH WAIT_AT_LOW_PRIORITY (ABORT_AFTER_WAIT=SELF), NO_INFOMSGS')
