from decimal import Decimal
from unittest.mock import patch
from django.test import SimpleTestCase, TestCase
from django.contrib.auth import get_user_model
from .analytics_store import fact_rows, number
from .dashboard_snapshots import cached_payload


class AnalyticalFactTests(SimpleTestCase):
    def test_revenue_and_customer_parts_are_queryable_separately(self):
        payload={'ready':True,'hero':{'revenue':100.01,'comparison_revenue':80},
            'business_lines':[{'code':'parts','revenue':75.01,'comparison_revenue':60},
                              {'code':'service','revenue':25,'comparison_revenue':20}],
            'dimensions':{'customers':[{'id':'A','name':'Customer A','revenue':100.01,
                'previous_revenue':80,'business_line_mix':{'parts':75.01,'service':25},
                'comparison_business_line_mix':{'parts':60,'service':20}}]},
            'trend':[{'date':'2026-09-01','value':100.01}]}
        rows=fact_rows('business',payload)
        self.assertEqual(rows['RevenueEntityLine'][0],('customers','A','parts',Decimal('75.01'),Decimal('60.00')))
        self.assertEqual(sum(r[1] for r in rows['RevenueSummary'][1:]),rows['RevenueSummary'][0][1])
        self.assertEqual(rows['RevenueTrend'][0][2],Decimal('100.01'))

    def test_failed_reconciliation_prevents_publication(self):
        with self.assertRaisesRegex(ValueError,'reconciliation'):
            fact_rows('business',{'ready':True,'hero':{'revenue':100},'business_lines':[{'code':'parts','revenue':90}]})

    def test_official_ratio_is_preserved_not_averaged_from_rows(self):
        rows=fact_rows('excellence',{'metric':{'code':'availability','unit':'%','raw_value':0.913456789},
            'breakdown':[{'entity':'A','metric_value':0.5},{'entity':'B','metric_value':1}],
            'summary':{'equipment_count':2,'formatted':'2'}})
        self.assertIn(('official','availability','%',Decimal('0.9134567890')),rows['ExcellenceMetric'])
        self.assertEqual(len(rows['ExcellenceDetail']),2)

    def test_null_and_zero_remain_distinct(self):
        self.assertIsNone(number(None))
        self.assertEqual(number(0),Decimal(0))
        for value in [float('nan'),float('inf'),True]:
            with self.assertRaises(ValueError):number(value)


class AnalyticalStorageRoutingTests(TestCase):
    def test_sql_read_does_not_fall_back_to_files_or_recalculate(self):
        user=get_user_model().objects.create_user('analytical-reader')
        stored={'generated_at':'2026-09-21T04:10:00+00:00','payload':{'value':12}}
        with patch('reports.dashboard_snapshots.configuration',return_value={'role':'origin','storage':'sqlserver'}), \
             patch('reports.dashboard_snapshots.directory'), \
             patch('reports.analytics_store.load',return_value=stored), \
             patch('reports.dashboard_snapshots._read',side_effect=AssertionError('File fallback')):
            payload=cached_payload('business',user,{}, {},lambda: self.fail('Unexpected rebuild'))
        self.assertEqual(payload['value'],12)
        self.assertIn('SQL Server',payload['dashboard_snapshot']['storage'])
