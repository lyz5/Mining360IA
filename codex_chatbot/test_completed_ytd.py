from datetime import date
from unittest.mock import patch
from django.test import SimpleTestCase
from .tools.performance_request import completed_ytd_period,monthly_windows,parse_request
from .tools.unified import performance_payload
from reports.homepage_availability_service import HomepageAvailabilityError


class CompletedYtdTests(SimpleTestCase):
    def test_current_month_is_excluded_even_on_its_last_day(self):
        for day in (1,29,30):
            self.assertEqual(completed_ytd_period('ytd',date(2026,9,day)),'custom:2026-01-01:2026-08-31')
        self.assertEqual(completed_ytd_period('ytd',date(2026,10,1)),'custom:2026-01-01:2026-09-30')

    def test_leap_year_and_january(self):
        self.assertEqual(completed_ytd_period('ytd',date(2024,3,1)),'custom:2024-01-01:2024-02-29')
        with self.assertRaises(ValueError):completed_ytd_period('ytd',date(2026,1,31))

    def test_explicit_periods_and_rolling_period_are_preserved(self):
        for period in ['custom:2026-09-01:2026-09-29','last_12_months']:
            self.assertEqual(completed_ytd_period(period,date(2026,9,29)),period)

    def test_monthly_ytd_has_no_partial_month(self):
        windows=monthly_windows('ytd',date(2026,9,29))
        self.assertEqual(len(windows),8)
        self.assertEqual(windows[-1],'custom:2026-08-01:2026-08-31')

    def test_french_since_year_start_is_ytd(self):
        self.assertEqual(parse_request("Disponibilité depuis le début de l'année",{},date(2026,9,29))[0]['period'],'ytd')

    @patch('codex_chatbot.tools.performance_request.timezone.localdate',return_value=date(2026,9,29))
    @patch('reports.dashboard_snapshots.enabled',return_value=True)
    @patch('reports.dashboard_snapshots.excellence_snapshot')
    def test_provider_sends_exact_closed_window_and_checks_returned_context(self,snapshot,enabled,today):
        snapshot.return_value={'context':{'period_code':'custom:2026-01-01:2026-08-31'}}
        result=performance_payload(object(),{'period':'ytd','metric':'availability','minesite':'SNIM-Guelb','model':'789'})
        self.assertEqual(snapshot.call_args.args[1]['period'],'custom:2026-01-01:2026-08-31')
        self.assertTrue(result['context']['ytd_complete_months'])
        snapshot.return_value={'context':{'period_code':'ytd'}}
        with self.assertRaises(HomepageAvailabilityError):performance_payload(object(),{'period':'ytd'})
