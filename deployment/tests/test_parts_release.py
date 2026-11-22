from datetime import date
from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from reports.models import PartSaleDetail,PartsSalesSynchronizationRun
from deployment.parts_sales_rollback_data import restore_parts

class ScopedPartsRollbackTests(TestCase):
    def setUp(self):
        old_run=PartsSalesSynchronizationRun.objects.create(status='Completed')
        self.new_run=PartsSalesSynchronizationRun.objects.create(status='Completed',source_context_json={'source':'Mine Logistics Report / FactSalesAllocation'})
        def row(source,amount,active,run,signature):
            return PartSaleDetail.objects.create(source_record_id=source,business_date=date(2026,10,1),
                allocated_revenue_eur=amount,source_hash=signature*64,active=active,synchronization_run=run,source_last_seen_at=timezone.now())
        self.old=row('legacy:0001','123.4567',False,old_run,'a')
        self.new=row('model:new','100',True,self.new_run,'b')
        self.baseline=[(self.old.pk,self.old.source_hash)]
        self.controls={'count':1,'amount':'123.4567'}

    def test_targeted_restore_keeps_new_rows_and_recovers_prior_precision(self):
        restore_parts(self.baseline,self.controls)
        self.old.refresh_from_db();self.new.refresh_from_db();self.new_run.refresh_from_db()
        self.assertTrue(self.old.active);self.assertFalse(self.new.active)
        self.assertEqual(self.old.allocated_revenue_eur,Decimal('123.4567'))
        self.assertEqual(PartSaleDetail.objects.count(),2)
        self.assertEqual(self.new_run.status,'Failed')

    def test_source_hash_drift_refuses_restoration_without_flag_changes(self):
        with self.assertRaises(RuntimeError):restore_parts([(self.old.pk,'x'*64)],self.controls)
        self.old.refresh_from_db();self.new.refresh_from_db()
        self.assertFalse(self.old.active);self.assertTrue(self.new.active)

    def test_control_failure_rolls_back_all_flag_and_run_changes(self):
        with self.assertRaises(RuntimeError):restore_parts(self.baseline,{'count':1,'amount':'999'})
        self.old.refresh_from_db();self.new.refresh_from_db();self.new_run.refresh_from_db()
        self.assertFalse(self.old.active);self.assertTrue(self.new.active)
        self.assertEqual(self.new_run.status,'Completed')
