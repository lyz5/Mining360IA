import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from .homepage_views import availability_command_center_api


class ExcellenceCompletedYtdTests(SimpleTestCase):
    def request(self, params, today=date(2026, 9, 29), allowed=True):
        request = RequestFactory().get('/api/home/availability-command-center/', params)
        request.user = SimpleNamespace(is_authenticated=True)
        with patch('reports.homepage_views._available', return_value=True), \
             patch('reports.homepage_views._authorized', return_value=allowed), \
             patch('reports.performance_periods.timezone.localdate', return_value=today), \
             patch('reports.dashboard_snapshots.excellence_snapshot') as provider:
            provider.side_effect = lambda user, p, **kw: {'context': {'period_code': p['period']}}
            response = availability_command_center_api(request)
        return response, provider

    def test_all_kpis_send_same_closed_dates_and_preserve_scope(self):
        for metric in ('availability', 'mtbf', 'mtbs', 'mttr', 'fuel'):
            with self.subTest(metric=metric):
                response, provider = self.request({'metric': metric, 'period': 'ytd',
                    'minesite': 'SNIM-Guelb', 'model': '789', 'refresh': '1'})
                self.assertEqual(response.status_code, 200)
                params = provider.call_args.args[1]
                self.assertEqual(params['period'], 'custom:2026-01-01:2026-08-31')
                self.assertEqual(params['minesite'], 'SNIM-Guelb')
                self.assertEqual(params['model'], '789')
                self.assertEqual(params['metric'], metric)
                self.assertTrue(provider.call_args.kwargs['force'])
                self.assertTrue(json.loads(response.content)['context']['ytd_complete_months'])

    def test_default_ytd_and_next_month_rollover(self):
        response, provider = self.request({}, today=date(2026, 10, 1))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(provider.call_args.args[1]['period'], 'custom:2026-01-01:2026-09-30')

    def test_january_has_no_closed_month_and_does_not_query(self):
        response, provider = self.request({'period': 'ytd'}, today=date(2026, 1, 31))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.content)['error_code'], 'no_completed_ytd_month')
        provider.assert_not_called()

    def test_other_periods_preserved(self):
        for period in ('last_12_months', 'custom:2026-09-01:2026-09-29'):
            response, provider = self.request({'period': period})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(provider.call_args.args[1]['period'], period)

    def test_access_denial_precedes_source_query(self):
        response, provider = self.request({'period': 'ytd'}, allowed=False)
        self.assertEqual(response.status_code, 403)
        provider.assert_not_called()
