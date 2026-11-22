from contextlib import nullcontext
from copy import deepcopy
from datetime import date, datetime, timezone as datetime_timezone
from decimal import Decimal
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.db.models import Sum
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from .models import PartSaleDetail, PartsSalesSynchronizationRun
from .parts_fulfillment_service import FulfillmentUnavailable
from .parts_sales_model_sync import PartsSalesModelSynchronizationService, SOURCE, page_query
from . import parts_sales_auto_sync as daily


class SourceFixture:
    def __init__(self):
        self.facts=[{'invoice_key':'22|22-01|000012','date':'2026-10-01','amount':'120'},
                    {'invoice_key':'22|22-01|000012','date':'2026-10-02','amount':'-20'}]
        self.accounts=[{**row,'account':'22-0007','company':'22','branch':'22-01','invoice':'000012'} for row in self.facts]
        self.lines=[{'invoice_key':'22|22-01|000012','part':'000A','brand':'CAT','weight':'3','quantity':'3','lines':2},
                    {'invoice_key':'22|22-01|000012','part':'000B','brand':'OTHER','weight':'1','quantity':'1','lines':1}]
        self.truncate=False
        self.fail=False

    def query(self, query):
        if self.fail: raise FulfillmentUnavailable('https://private.invalid/?sig=secret')
        if '"first"' in query: return [{'first':'2026-10-01','last':'2026-10-02'}]
        periods=re.findall(r'DATE\((\d+),(\d+),(\d+)\)',query)
        start,end=[date(*(int(v) for v in item)) for item in periods[:2]]
        facts=[r for r in self.facts if start<=date.fromisoformat(r['date'])<=end]
        accounts=[r for r in self.accounts if start<=date.fromisoformat(r['date'])<=end]
        keys={r['invoice_key'] for r in facts}
        lines=[r for r in self.lines if r['invoice_key'] in keys]
        if '"accounting_count"' in query:
            return [{'accounting_count':len(facts),'account_count':len(accounts),'line_count':len(lines),
                     'sales':str(sum((Decimal(r['amount']) for r in facts if r.get('amount') is not None),Decimal(0))),
                     'latest':max((r['date'] for r in facts),default=None)}]
        if 'SELECTCOLUMNS(GROUPBY(Facts,' in query: rows=facts
        elif 'SELECTCOLUMNS(GROUPBY(Accounts,' in query: rows=accounts
        elif 'SELECTCOLUMNS(GROUPBY(Lines,' in query: rows=lines
        else: raise AssertionError('Unexpected source query')
        rows=[{**r,'cursor':f'{i:06d}'} for i,r in enumerate(rows,1)]
        if self.truncate: rows=rows[:-1]
        return rows


class PartsSalesModelImportTests(TestCase):
    def setUp(self):
        self.folder=TemporaryDirectory(); self.addCleanup(self.folder.cleanup)
        config=override_settings(PARTS_SALES_STATE_DIRECTORY=self.folder.name)
        config.enable(); self.addCleanup(config.disable)
        self.source=SourceFixture()
        self.service=PartsSalesModelSynchronizationService(None,source=self.source)
        self.old_run=PartsSalesSynchronizationRun.objects.create(status='Completed',data_through_date=date(2026,10,2),completed_at=timezone.now())
        self.old=PartSaleDetail.objects.create(source_record_id='legacy',business_date=date(2026,10,1),
            invoice_number='000012',part_number='OLD',normalized_part_number='OLD',allocated_revenue_eur='999',
            source_hash='a'*64,synchronization_run=self.old_run,source_last_seen_at=timezone.now())

    def run_import(self):
        return self.service.synchronize(date(2026,10,1),date(2026,10,31))

    def test_value_conservation_credits_dates_and_text_keys(self):
        run=self.run_import()
        rows=list(PartSaleDetail.objects.filter(active=True).order_by('business_date','part_number'))
        self.assertEqual([r.allocated_revenue_eur for r in rows],[Decimal('90'),Decimal('30'),Decimal('-15'),Decimal('-5')])
        self.assertEqual(run.allocated_revenue_eur,Decimal('100'))
        self.assertEqual({r.invoice_key for r in rows},{'22|22-01|000012'})
        self.assertEqual({r.invoice_number for r in rows},{'000012'})
        self.assertEqual({r.customer_code for r in rows},{'22-0007'})
        self.assertEqual(sum(r.source_line_count for r in rows),6)
        self.assertEqual(run.data_through_date,date(2026,10,2))
        self.old.refresh_from_db(); self.assertFalse(self.old.active)

    def test_repeat_import_is_idempotent_and_retains_the_last_result(self):
        self.run_import(); count=PartSaleDetail.objects.count()
        run=self.run_import()
        self.assertEqual(PartSaleDetail.objects.count(),count)
        self.assertEqual(run.records_unchanged,4)
        self.assertEqual(run.records_created,0)
        self.assertEqual(PartSaleDetail.objects.filter(active=True).aggregate(total=Sum('allocated_revenue_eur'))['total'],Decimal('100'))

    def test_source_failure_retains_previous_rows_and_does_not_log_secret(self):
        self.source.truncate=True
        with self.assertRaises(FulfillmentUnavailable): self.run_import()
        self.old.refresh_from_db(); self.assertTrue(self.old.active)
        latest=PartsSalesSynchronizationRun.objects.first()
        self.assertEqual(latest.status,'Failed'); self.assertNotIn('secret',latest.error_message)
        self.assertFalse(list(Path(self.folder.name).glob('stage-*.jsonl')))

    def test_atomic_activation_rolls_back_database_write_failure(self):
        from .parts_sales_service import PartsSalesSynchronizationService
        original=PartsSalesSynchronizationService._persist
        def fail_after_persist(*args,**kwargs):
            original(*args,**kwargs)
            raise RuntimeError('Simulated local write failure')
        with patch.object(PartsSalesSynchronizationService,'_persist',side_effect=fail_after_persist):
            with self.assertRaises(RuntimeError): self.run_import()
        self.assertEqual(PartSaleDetail.objects.count(),1)
        self.old.refresh_from_db(); self.assertTrue(self.old.active)

    def test_missing_line_invoice_is_unmatched_without_inventing_a_row(self):
        self.source.lines=[]
        run=self.run_import()
        self.assertEqual(run.records_read,0)
        self.assertEqual(run.source_context_json['exceptions']['no_lines'],2)
        self.assertEqual(run.source_context_json['accounting_total'],'100')
        self.assertFalse(PartSaleDetail.objects.filter(active=True).exists())

    def test_zero_signed_weight_does_not_force_an_allocation(self):
        self.source.lines[1]['weight']='-3'
        run=self.run_import()
        self.assertEqual(run.source_context_json['exceptions']['zero_weight'],2)
        self.assertEqual(run.allocated_revenue_eur,0)

    def test_missing_or_ambiguous_customer_cannot_leak_to_an_account(self):
        self.source.accounts[0]['amount']='70'
        self.source.accounts.append({**self.source.accounts[0],'account':'22-9999','amount':'50'})
        run=self.run_import()
        self.assertEqual(run.source_context_json['exceptions']['ambiguous_customer'],1)
        self.assertEqual(run.allocated_revenue_eur,Decimal('-20'))

    def test_accounting_customer_ledger_must_reconcile_per_invoice_date(self):
        self.source.accounts[0]['amount']='119'
        with self.assertRaises(FulfillmentUnavailable): self.run_import()
        self.old.refresh_from_db(); self.assertTrue(self.old.active)

    def test_rounding_residual_is_conserved_per_invoice_date(self):
        self.source.facts[0]['amount']='0.01'; self.source.accounts[0]['amount']='0.01'
        self.source.lines[0]['weight']='1'; self.source.lines[1]['weight']='2'
        run=self.run_import()
        self.assertEqual(run.allocated_revenue_eur,Decimal('-19.99'))

    def test_invalid_nonfinite_source_values_fail_closed(self):
        self.source.lines[0]['weight']='NaN'
        with self.assertRaises(FulfillmentUnavailable): self.run_import()
        self.old.refresh_from_db(); self.assertTrue(self.old.active)

    def test_accounting_dates_outside_requested_window_are_rejected(self):
        with self.assertRaises(ValueError): self.service.synchronize(date(2026,10,31),date(2026,10,1))

    def test_fractional_cent_accounting_precision_is_preserved(self):
        self.source.facts[0]['amount']='0.00005'
        self.source.accounts[0]['amount']='0.00005'
        run=self.run_import()
        self.assertEqual(run.allocated_revenue_eur,Decimal('-19.99995'))
        self.assertEqual(PartSaleDetail.objects.filter(active=True).aggregate(value=Sum('allocated_revenue_eur'))['value'],Decimal('-19.99995'))

    @patch('reports.parts_sales_model_sync.time.sleep')
    def test_failure_before_first_page_is_recorded_for_retry_backoff(self,sleep):
        self.source.fail=True
        with self.assertRaises(FulfillmentUnavailable): self.run_import()
        run=PartsSalesSynchronizationRun.objects.first()
        self.assertEqual(run.status,'Failed')
        self.assertNotIn('sig=',run.error_message)
        self.old.refresh_from_db();self.assertTrue(self.old.active)

    def test_customer_restrictions_apply_to_imported_rows(self):
        from .parts_sales_service import PartsSalesDetailService
        self.run_import()
        with patch('reports.parts_sales_service.authorized_account_codes',return_value={'22-9999'}):
            result=PartsSalesDetailService(None,{'start_date':'2026-10-01','end_date':'2026-10-31'}).result()
            self.assertEqual(result['results'],[])
            self.assertEqual(result['summary']['allocated_invoice_revenue_eur'],0)
        with patch('reports.parts_sales_service.authorized_account_codes',return_value={'22-0007'}):
            result=PartsSalesDetailService(None,{'start_date':'2026-10-01','end_date':'2026-10-31'}).result()
            self.assertEqual(result['summary']['allocated_invoice_revenue_eur'],100)

    def test_duplicate_page_identifiers_are_rejected(self):
        rows=[{'invoice_key':'a','cursor':'duplicate'},{'invoice_key':'b','cursor':'duplicate'}]
        with patch.object(self.source,'query',return_value=rows):
            with self.assertRaises(FulfillmentUnavailable):self.service.read('lines',date(2026,10,1),date(2026,10,31),2)

    def test_missing_catalog_cannot_erase_previously_classified_parts(self):
        self.old.classification_status='Classified';self.old.brand_group='CAT';self.old.major_class_code='7';self.old.save()
        with self.assertRaises(FulfillmentUnavailable) as failure:self.run_import()
        self.assertEqual(failure.exception.code,'CLASSIFICATION_REFERENCE_REQUIRED')
        self.old.refresh_from_db();self.assertTrue(self.old.active)
        self.assertEqual(self.old.major_class_code,'7')

    def test_source_blank_accounting_rows_are_reported_without_becoming_allocations(self):
        self.source.facts[0]['amount']=None;self.source.accounts[0]['amount']=None
        run=self.run_import()
        self.assertEqual(run.allocated_revenue_eur,Decimal('-20'))
        self.assertEqual(run.source_context_json['exceptions']['blank_accounting'],1)
        self.assertEqual(run.records_read,2)

    def test_same_invoice_number_in_different_branches_does_not_multiply_sales(self):
        row={'invoice_key':'22|22-02|000012','date':'2026-10-01','amount':'50'}
        self.source.facts.append(row)
        self.source.accounts.append({**row,'account':'22-0042','company':'22','branch':'22-02','invoice':'000012'})
        self.source.lines.append({'invoice_key':row['invoice_key'],'part':'000A','brand':'CAT','weight':'4','quantity':'4','lines':1})
        run=self.run_import()
        self.assertEqual(run.allocated_revenue_eur,Decimal('150'))
        query=PartSaleDetail.objects.filter(active=True,invoice_key=row['invoice_key'])
        self.assertEqual(query.count(),1)
        self.assertEqual(query.get().allocated_revenue_eur,Decimal('50'))


class PartsSourceQueryTests(SimpleTestCase):
    def test_query_uses_existing_keys_all_dates_and_signed_extended_line_value(self):
        query=page_query('lines',date(2026,10,1),date(2026,10,31),'a"b')
        self.assertIn('[INVOICEKEY_V2]',query)
        self.assertIn('[NLLF_QTEFAC]*',query)
        self.assertIn('[NLLF_PXNREEL]',query)
        self.assertIn('a""b',query)
        self.assertNotIn('NLLF_DATEPIC',query)
        self.assertNotIn('PQ_SingleOrderInvoices',query)
        self.assertIn('[Code Soci\u00e9t\u00e9]',page_query('accounts',date(2026,10,1),date(2026,10,31)))
        self.assertNotIn('\u00c3',page_query('accounts',date(2026,10,1),date(2026,10,31)))

    @patch('reports.parts_sales_model_sync.LogisticsSource',side_effect=FulfillmentUnavailable('No verified scope','SCOPED_QUERY_NOT_CONFIGURED'))
    def test_import_cannot_bypass_the_existing_source_scope(self,source):
        with self.assertRaises(FulfillmentUnavailable): PartsSalesModelSynchronizationService(object())


@override_settings(PARTS_SALES_AUTO_SYNC=True,BUSINESS_REVENUE_AUTO_SYNC_HOUR=5,BUSINESS_REVENUE_AUTO_SYNC_MINUTE=0,
    BUSINESS_REVENUE_AUTO_SYNC_TIME_ZONE='Etc/GMT',BUSINESS_REVENUE_AUTO_SYNC_RETRY_MINUTES=60)
class PartsClassificationScheduleTests(TestCase):
    at_five=datetime(2026,11,19,5,tzinfo=datetime_timezone.utc)

    def setUp(self):
        role=patch('reports.dashboard_snapshots.configuration',return_value={'role':'disabled'})
        role.start(); self.addCleanup(role.stop)
        self.user=get_user_model().objects.create_superuser('sync-owner','sync@example.com','test-password')
        auth=patch('reports.parts_fulfillment_views.allowed',return_value=True)
        auth.start(); self.addCleanup(auth.stop)

    @patch.object(daily,'PartsSalesModelSynchronizationService')
    def test_no_source_queries_before_five_am(self,service):
        self.assertFalse(daily.synchronize_if_due(self.at_five.replace(hour=4)))
        service.assert_not_called()

    @patch.object(daily,'PartsSalesModelSynchronizationService')
    def test_first_slot_uses_existing_authorized_identity(self,service):
        self.assertTrue(daily.synchronize_if_due(self.at_five))
        service.assert_called_once_with(self.user)
        service.return_value.synchronize.assert_called_once_with()

    @patch.object(daily,'PartsSalesModelSynchronizationService')
    def test_completed_import_satisfies_the_daily_slot(self,service):
        run=PartsSalesSynchronizationRun.objects.create(status='Completed',source_context_json={'source':SOURCE},completed_at=self.at_five)
        self.assertFalse(daily.synchronize_if_due(self.at_five.replace(hour=8)))
        service.assert_not_called()

    @patch.object(daily,'PartsSalesModelSynchronizationService')
    def test_source_failure_keeps_data_and_applies_retry_backoff(self,service):
        run=PartsSalesSynchronizationRun.objects.create(status='Failed',source_context_json={'source':SOURCE})
        PartsSalesSynchronizationRun.objects.filter(pk=run.pk).update(started_at=self.at_five)
        self.assertFalse(daily.synchronize_if_due(self.at_five.replace(minute=30)))
        service.assert_not_called()

    @patch.object(daily,'PartsSalesModelSynchronizationService')
    @patch.object(daily,'is_platform_admin',return_value=False)
    def test_restricted_users_are_never_used_to_refresh_global_data(self,admin,service):
        self.assertFalse(daily.synchronize_if_due(self.at_five))
        service.assert_not_called()
