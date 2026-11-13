from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.test import SimpleTestCase, RequestFactory, override_settings

from .parts_fulfillment_service import (
    COHORTS, MEASURES, FulfillmentUnavailable, LogisticsSource, PartsFulfillmentService,
    dax_text, monthly_dax, reconciliation,
)
from . import parts_fulfillment_views as views


def october(month='2026-10'):
    # Historical acceptance reference supplied by the user, used only in tests.
    return {'MonthStart': month+'-01T00:00:00', 'orders': '124490000', 'sales': '20100153.90',
            'current': '8416346.36', 'last': '4817567.64', 'older': '6047941.69',
            'unallocated': '818298.21', 'future': '0', 'difference': '0.00', 'coverage': month+'-31'}


class FulfillmentFinancialTests(SimpleTestCase):
    def service(self, rows, today=date(2026, 11, 13)):
        self.source = Mock()
        self.source.cached_query.return_value = rows
        return PartsFulfillmentService(SimpleNamespace(pk=7), source=self.source, today=today)

    def test_october_reconciles_without_confusing_realization_and_sales_share(self):
        with override_settings(PARTS_FULFILLMENT_COMPARABILITY_CONFIRMED=True):
            data=self.service([october()]).summary()
        self.assertEqual(data['selected_month'],'2026-10')
        self.assertEqual(data['kpis']['reconciliation']['status'],'reconciled')
        self.assertEqual(Decimal(data['older_sales']),Decimal('10865509.33'))
        self.assertAlmostEqual(float(data['realization_percent']),6.76066058,places=5)
        self.assertAlmostEqual(Decimal(data['kpis']['current'])/Decimal(data['kpis']['sales'])*100,Decimal('41.87205'),places=4)

    def test_comparability_is_required_for_realization(self):
        with override_settings(PARTS_FULFILLMENT_COMPARABILITY_CONFIRMED=False):
            self.assertIsNone(self.service([october()]).summary()['realization_percent'])

    def test_last_completed_month_not_current_is_default(self):
        data=self.service([october(),october('2026-11')]).summary()
        self.assertEqual(data['selected_month'],'2026-10')
        data=self.service([october(),october('2026-11')]).summary('2026-11')
        self.assertTrue(data['month_to_date'])
        self.assertIsNone(data['changes']['sales']['percent'])
        self.assertIn('elapsed',data['changes']['sales']['reason'])

    def test_history_uses_calendar_window_and_does_not_fill_gaps(self):
        rows=[october(m) for m in ['2025-09','2025-11','2026-01','2026-10']]
        data=self.service(rows).summary('2026-10')
        self.assertEqual([r['month'] for r in data['series']],['2025-11','2026-01','2026-10'])
        self.assertIsNone(data['changes']['orders']['percent'])

    def test_negative_and_zero_previous_values_do_not_produce_misleading_growth(self):
        previous=october('2026-09');previous['orders']='-5';previous['sales']='0'
        data=self.service([previous,october()]).summary()
        self.assertIsNone(data['changes']['orders']['percent'])
        self.assertIsNone(data['changes']['sales']['percent'])

    def test_future_cohort_and_credits_stay_in_total(self):
        row=october();row.update(sales='75',current='100',last='-30',older='0',unallocated='0',future='5')
        data=self.service([row]).summary()
        self.assertEqual(data['kpis']['future'],'5')
        self.assertEqual(data['kpis']['last'],'-30')
        self.assertEqual(data['kpis']['reconciliation']['status'],'reconciled')

    def test_source_and_arithmetic_warnings_do_not_adjust_values(self):
        row=october();row['sales']='20100155'
        data=self.service([row]).summary()
        self.assertEqual(data['kpis']['sales'],'20100155')
        self.assertEqual(data['kpis']['reconciliation']['status'],'warning')
        row=october();row['difference']='.02'
        self.assertEqual(self.service([row]).summary()['kpis']['reconciliation']['status'],'warning')

    def test_empty_source_and_missing_month_are_explicit(self):
        self.assertTrue(self.service([]).summary()['empty'])
        data=self.service([october()]).summary('2026-09')
        self.assertTrue(data['empty']);self.assertNotIn('kpis',data)

    def test_invalid_month_is_rejected(self):
        with self.assertRaises(ValueError):self.service([october()]).summary('2026-13')

    def test_missing_metric_is_not_a_valid_reconciliation(self):
        row=october();del row['difference']
        self.assertEqual(self.service([row]).summary()['kpis']['reconciliation']['status'],'unavailable')

    def test_valid_blank_cohort_is_explicit_and_not_a_loading_error(self):
        row=october();row['future']=None
        data=self.service([row]).summary()
        self.assertEqual(data['kpis']['future'],'0')
        self.assertEqual(data['kpis']['blank_cohorts'],['future'])
        self.assertEqual(data['kpis']['reconciliation']['status'],'reconciled')

    def test_transport_error_never_becomes_zero_sales(self):
        service=self.service([])
        self.source.cached_query.side_effect=FulfillmentUnavailable('unavailable')
        with self.assertRaises(FulfillmentUnavailable):service.summary()

    def test_query_reuses_all_source_measures_and_does_not_group_orders_from_invoices(self):
        query=monthly_dax(date(2026,11,13))
        for name in MEASURES.values():self.assertIn(f'[{name}]',query)
        self.assertNotIn('InvoiceKey',query)
        self.assertIn("'Date'[Date]",query)


class FulfillmentDetailTests(SimpleTestCase):
    def setUp(self):
        self.source=Mock()
        self.source.cached_query.return_value=[{'kind':'meta','total_rows':1,'detail_total':'12.50','measure_total':'12.50'},
            {'kind':'row','accounting_date':'2026-10-20T00:00:00','order_date':None,'order_key':None,
             'invoice_key':'22|22-01|000123','cohort':'Unallocated','amount':'12.50'}]
        self.service=PartsFulfillmentService(SimpleNamespace(pk=7),source=self.source,today=date(2026,11,13))

    def test_unallocated_detail_keeps_absent_order_and_complete_text_invoice_key(self):
        data=self.service.details({'month':'2026-10','cohort':'unallocated'})
        self.assertIsNone(data['rows'][0]['order_key'])
        self.assertEqual(data['rows'][0]['invoice_key'],'22|22-01|000123')
        self.assertEqual(data['reconciliation'],'reconciled')

    def test_search_quotes_and_wildcards_are_literals_and_pagination_is_stable(self):
        self.service.details({'month':'2026-10','search':'00"*?','page':'2','sort':'amount'})
        query=self.source.cached_query.call_args.args[0]
        self.assertIn('00""~*~?',query)
        self.assertIn('TOPN(50,Rows',query);self.assertIn('TOPN(25,Rows',query)
        for key in ['order_key','invoice_key','order_date','accounting_date','cohort']:self.assertIn(f'[{key}],ASC',query)
        self.assertNotIn('LOOKUPVALUE',query)

    def test_export_ignores_visible_page_and_rejects_partial_export(self):
        self.service.details({'month':'2026-10','page':'4'},export=True)
        self.assertIn('TOPN(10001,Rows',self.source.cached_query.call_args.args[0])
        self.source.cached_query.return_value[0]['total_rows']=10001
        with self.assertRaisesRegex(ValueError,'no partial export'):
            self.service.details({'month':'2026-10'},export=True)

    def test_invalid_cohort_sort_page_or_long_search_rejected_before_query(self):
        for params in [{'cohort':'injected'},{'sort':'anything'},{'direction':'anything'},{'page':'0'},{'search':'a'*101}]:
            with self.assertRaises(ValueError):self.service.details({'month':'2026-10',**params})
        self.source.cached_query.assert_not_called()

    def test_numeric_keys_fail_closed_instead_of_losing_initial_zeros(self):
        self.source.cached_query.return_value[1]['invoice_key']=123
        with self.assertRaises(FulfillmentUnavailable):self.service.details({'month':'2026-10'})

    def test_detail_quality_warning_is_independent_of_top_kpis(self):
        self.source.cached_query.return_value[0]['measure_total']='14'
        data=self.service.details({'month':'2026-10'})
        self.assertEqual(data['total'],'12.50');self.assertEqual(data['reconciliation'],'warning')


class FulfillmentSecurityTests(SimpleTestCase):
    def setUp(self):cache.clear()

    @patch('reports.parts_fulfillment_service.report_for')
    @patch('reports.parts_fulfillment_service.is_platform_admin',return_value=False)
    @patch('reports.parts_fulfillment_service.authorized_account_codes',return_value={'customer-a'})
    @patch('reports.parts_fulfillment_service.authorized_minesite_names',return_value={'site-a'})
    def test_restricted_query_cannot_use_shared_identity(self,*mocks):
        with self.assertRaises(FulfillmentUnavailable) as raised:LogisticsSource(SimpleNamespace(pk=1))
        self.assertEqual(raised.exception.code,'SCOPED_QUERY_NOT_CONFIGURED')

    @patch('reports.parts_fulfillment_service.authorized_account_codes',return_value=None)
    @patch('reports.parts_fulfillment_service.authorized_minesite_names',return_value=None)
    def test_cached_queries_are_partitioned_by_user_and_report_revision(self,*mocks):
        source=object.__new__(LogisticsSource)
        source.user=SimpleNamespace(pk=1)
        source.report=SimpleNamespace(pk=2,semantic_model_id='configured-model',updated_at=datetime(2026,1,1,tzinfo=timezone.utc),configuration_version=1,authentication_mode='app_owns_data',default_rls_role='Global')
        source.query=Mock(return_value=[{'value':1}]);source.cached_query('query');source.cached_query('query')
        self.assertEqual(source.query.call_count,1)
        source.user=SimpleNamespace(pk=2);source.cached_query('query');self.assertEqual(source.query.call_count,2)
        source.report.configuration_version=2;source.cached_query('query');self.assertEqual(source.query.call_count,3)
        source.refresh_id='new-source-run';source.cached_query('query');self.assertEqual(source.query.call_count,4)

    @patch('reports.parts_fulfillment_service.power_automate.get_flow_url',return_value='configured-flow-not-a-real-url')
    @patch('reports.parts_fulfillment_service.power_automate.HTTP.post')
    def test_partial_source_error_is_rejected_and_not_cached(self,post,_flow):
        source=object.__new__(LogisticsSource);source.report=SimpleNamespace(report_name='Mine Logistics Report',semantic_model_id='configured-model')
        post.return_value.status_code=200
        post.return_value.json.return_value={'results':[{'tables':[{'rows':[{'[sales]':42}],'error':{'code':'Truncated'}}]}]}
        with self.assertRaises(FulfillmentUnavailable):source.query('query')

    @patch('reports.parts_fulfillment_service.power_automate.get_flow_url',return_value='configured-flow-not-a-real-url')
    @patch('reports.parts_fulfillment_service.power_automate.HTTP.post')
    def test_source_authorization_error_is_explicit(self,post,_flow):
        source=object.__new__(LogisticsSource);source.report=SimpleNamespace(report_name='Mine Logistics Report',semantic_model_id='configured-model')
        post.return_value.status_code=403
        with self.assertRaises(FulfillmentUnavailable) as raised:source.query('query')
        self.assertEqual(raised.exception.code,'SOURCE_AUTHORIZATION_REQUIRED')

    def test_forbidden_view_never_queries_source(self):
        request=RequestFactory().get('/api/business-review/parts-fulfillment/summary/')
        request.user=SimpleNamespace(is_authenticated=True)
        with patch.object(views,'allowed',return_value=False),patch.object(views,'PartsFulfillmentService') as service:
            response=views.summary(request)
        self.assertEqual(response.status_code,403);service.assert_not_called()

    def test_export_requires_own_export_permission_and_error_does_not_leak(self):
        request=RequestFactory().get('/api/business-review/parts-fulfillment/export/')
        request.user=SimpleNamespace(is_authenticated=True)
        with patch.object(views,'allowed',return_value=True),patch.object(views,'has_business_review_permission',return_value=False),patch.object(views,'PartsFulfillmentService') as service:
            self.assertEqual(views.export(request).status_code,403);service.assert_not_called()
        response=views.error_response(RuntimeError('secret signed URL'))
        self.assertNotIn(b'signed',response.content)
        self.assertEqual(response.status_code,503)
        self.assertIn('no-store',response['Cache-Control'])

    def test_csv_text_does_not_execute_formulas(self):
        self.assertEqual(views.csv_text('=HYPERLINK("bad")'),'\'=HYPERLINK("bad")')
        self.assertEqual(views.csv_text('001|22|01'),'001|22|01')
