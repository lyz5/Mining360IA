from copy import deepcopy
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

from django.test import SimpleTestCase

from .parts_fulfillment_service import PartsFulfillmentService, FulfillmentUnavailable


def monthly(month, orders='120', sales='60', coverage=None):
    return {'MonthStart':month+'-01','orders':orders,'sales':sales,'current':'30',
            'last':'20','older':'10','unallocated':None,'future':None,'difference':'0',
            'coverage':coverage}


class CurrentMonthComparisonTests(SimpleTestCase):
    def setUp(self):
        self.rows=[monthly('2026-10','400','300','2026-10-31'),
                   monthly('2026-11',coverage='2026-11-20')]
        self.previous={'orders':'100','sales':'50'}
        self.source=Mock(last_refresh=None)
        self.source.cached_query.side_effect=self.query

    def query(self,dax,**kwargs):
        if dax.startswith('EVALUATE ROW('):
            if isinstance(self.previous,Exception):raise self.previous
            return deepcopy([self.previous])
        return deepcopy(self.rows)

    def summary(self,selected=None,today=date(2026,11,24),**kwargs):
        return PartsFulfillmentService(SimpleNamespace(pk=1),source=self.source,today=today).summary(selected,**kwargs)

    def test_default_is_current_month_and_history_remains_available(self):
        data=self.summary()
        self.assertEqual(data['selected_month'],'2026-11')
        self.assertTrue(data['month_to_date'])
        self.assertEqual([row['month'] for row in data['series']],['2026-10','2026-11'])
        self.assertEqual(data['kpis']['sales'],'60')
        self.assertEqual(data['kpis']['unallocated'],'0')
        self.assertEqual(data['kpis']['reconciliation']['status'],'reconciled')

    def test_comparison_uses_elapsed_orders_and_known_accounting_coverage(self):
        data=self.summary();orders=data['changes']['orders'];sales=data['changes']['sales']
        self.assertEqual((orders['current_end'],orders['previous_end']),('2026-11-24','2026-10-24'))
        self.assertEqual((sales['current_end'],sales['previous_end']),('2026-11-20','2026-10-20'))
        self.assertEqual(orders['previous_value'],'100')
        self.assertEqual(sales['previous_month_total'],'300')
        self.assertEqual(orders['percent'],'20.0')
        self.assertEqual(sales['percent'],'20.0')
        self.assertEqual(sales['absolute_difference'],'10')
        dax=self.source.cached_query.call_args.args[0]
        self.assertIn('[Order Intake EUR]',dax);self.assertIn('[CA Comptable EUR]',dax)
        self.assertIn('DATE(2026,10,24)',dax);self.assertIn('DATE(2026,10,20)',dax)
        self.assertNotIn('InvoiceKey',dax)

    def test_explicit_past_month_keeps_full_month_comparison_without_extra_query(self):
        self.rows.insert(0,monthly('2026-09','200','100','2026-09-30'))
        data=self.summary('2026-10')
        self.assertEqual(data['selected_month'],'2026-10')
        self.assertFalse(data['month_to_date'])
        self.assertEqual(data['changes']['orders']['percent'],'100')
        self.assertEqual(data['changes']['sales']['previous_end'],'2026-09-30')
        self.assertEqual(data['changes']['sales']['basis'],'calendar_month')
        self.assertEqual(self.source.cached_query.call_count,1)

    def test_current_month_without_data_is_explicit_instead_of_selecting_october(self):
        self.rows=self.rows[:1]
        data=self.summary()
        self.assertTrue(data['empty']);self.assertEqual(data['selected_month'],'2026-11')
        self.assertEqual(data['months'],['2026-10']);self.assertEqual(data['series'],[])
        self.assertNotIn('kpis',data)

    def test_empty_source_retains_current_month_context(self):
        self.rows=[]
        data=self.summary()
        self.assertTrue(data['empty']);self.assertEqual(data['current_month'],'2026-11')
        self.assertEqual(data['selected_month'],'2026-11')

    def test_blank_current_value_is_not_a_zero_or_a_percentage(self):
        self.rows[-1]['orders']=None
        change=self.summary()['changes']['orders']
        self.assertIsNone(change['current_value']);self.assertIsNone(change['percent'])

    def test_zero_negative_or_absent_previous_value_never_produces_a_percentage(self):
        for value in ('0','-12',None):
            with self.subTest(value=value):
                self.previous['sales']=value
                change=self.summary()['changes']['sales']
                self.assertIsNone(change['percent']);self.assertTrue(change['reason'])
                self.assertEqual(change['previous_value'],value)

    def test_negative_current_value_remains_signed(self):
        self.rows[-1]['sales']='-10'
        change=self.summary()['changes']['sales']
        self.assertEqual(change['percent'],'-120.0')
        self.assertEqual(change['absolute_difference'],'-60')

    def test_previous_period_failure_preserves_actual_values_without_exposing_source_error(self):
        self.previous=FulfillmentUnavailable('https://private.invalid/?sig=secret')
        data=self.summary()
        self.assertEqual(data['kpis']['orders'],'120');self.assertEqual(data['kpis']['sales'],'60')
        self.assertIsNone(data['changes']['sales']['previous_value'])
        self.assertIsNone(data['changes']['sales']['percent'])
        self.assertNotIn('secret',str(data))

    def test_missing_previous_month_is_unavailable_and_does_not_invent_a_period(self):
        self.rows=self.rows[1:]
        data=self.summary()
        self.assertIsNone(data['changes']['orders']['percent'])
        self.assertEqual(self.source.cached_query.call_count,1)

    def test_shorter_previous_month_and_leap_day_are_explicit(self):
        for year,end in ((2026,'2026-02-28'),(2024,'2024-02-29')):
            with self.subTest(year=year):
                self.rows=[monthly(f'{year}-02'),monthly(f'{year}-03')]
                change=self.summary(today=date(year,3,31))['changes']['orders']
                self.assertEqual(change['previous_end'],end)
                self.assertEqual(change['current_end'],f'{year}-03-31')
                self.assertIsNone(change['percent'])
                self.assertIn('no matching calendar day',change['reason'])

    def test_january_uses_previous_december(self):
        self.rows=[monthly('2025-12'),monthly('2026-01')]
        data=self.summary(today=date(2026,1,2))
        self.assertEqual(data['changes']['sales']['previous_start'],'2025-12-01')
        self.assertEqual(data['changes']['sales']['previous_end'],'2025-12-02')

    def test_unknown_coverage_uses_explicit_calendar_mtd_not_an_invented_timestamp(self):
        self.rows[-1]['coverage']=None
        data=self.summary()
        self.assertIsNone(data['source']['coverage'])
        self.assertEqual(data['changes']['sales']['current_end'],'2026-11-24')

    def test_force_refresh_applies_to_both_queries(self):
        self.summary(force_refresh=True)
        self.assertEqual(self.source.cached_query.call_count,2)
        for call in self.source.cached_query.call_args_list:self.assertEqual(call.kwargs,{'force':True})

    def test_invalid_coverage_cannot_create_a_comparison_with_future_accounting_dates(self):
        self.rows[-1]['coverage']='2026-11-30'
        with self.assertRaises(FulfillmentUnavailable):self.summary()

    def test_twelve_month_history_ends_at_selected_current_month(self):
        self.rows=[monthly('2025-10'),monthly('2025-11'),monthly('2025-12')]+[
            monthly(f'2026-{month:02d}') for month in range(1,12)]
        data=self.summary()
        self.assertEqual(len(data['series']),12)
        self.assertEqual(data['series'][0]['month'],'2025-12')
        self.assertEqual(data['series'][-1]['month'],'2026-11')
