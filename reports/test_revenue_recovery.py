from datetime import date
from unittest.mock import patch
from django.test import TestCase
from django.utils import timezone
from .business_mapping_source_service import BusinessMappingSourceSynchronizationService, BusinessMappingSourceError
from .business_mapping_country_account_service import CountryAccountService
from .business_mapping_normalization_service import normalize_business_name
from .models import BusinessAccount, BusinessCompanyCodeReference, CountryAccount, CountryAccountMembership, MappingSynchronizationRun, RevenueSourceSnapshot

class RevenueRecoveryTests(TestCase):
    def setUp(self):
        self.old = MappingSynchronizationRun.objects.create(status="Completed")
        self.row = RevenueSourceSnapshot.objects.create(
            synchronization_run=self.old, source_record_id="old", source_hash="old",
            division="MI", business_date=date(2026, 9, 21), source_last_seen_at=timezone.now(),
            revenue_eur=100, active=True,
        )
        self.service = BusinessMappingSourceSynchronizationService(None)

    def incoming(self, **overrides):
        return {"division": "MI", "business_date": 20260925, "source_account_code": "1",
                "source_account_name": "Example", "lob": "PARTS", "period_year": 2026,
                "revenue_eur": 150, **overrides}

    def commit(self, rows, accounts=None):
        run = MappingSynchronizationRun.objects.create(status="Queued")
        self.service._source_warnings = []
        return self.service._commit_snapshot(run, accounts or [], [], rows, [], "test-model")

    def test_empty_response_preserves_current_revenue(self):
        with self.assertRaises(BusinessMappingSourceError):
            self.commit([])
        self.row.refresh_from_db()
        self.assertTrue(self.row.active)
        self.assertEqual(RevenueSourceSnapshot.objects.count(), 1)

    def test_excluded_only_response_cannot_erase_revenue(self):
        with self.assertRaises(BusinessMappingSourceError):
            self.commit([self.incoming(distribution_channel="INTERCO")])
        self.row.refresh_from_db()
        self.assertTrue(self.row.active)

    def test_invalid_dates_preserve_previous_data(self):
        with self.assertRaises(BusinessMappingSourceError):
            self.commit([self.incoming(business_date="invalid")])
        self.row.refresh_from_db()
        self.assertTrue(self.row.active)

    def test_missing_division_preserves_previous_data(self):
        with self.assertRaises(BusinessMappingSourceError):
            self.commit([self.incoming(division="MO")])
        self.row.refresh_from_db()
        self.assertTrue(self.row.active)

    def test_grouping_uses_country_from_current_revenue(self):
        BusinessCompanyCodeReference.objects.create(
            company_code="TEST", legal_entity_name="Example", operating_country_code="CI")
        account = BusinessAccount.objects.create(canonical_account_code="MININGACCOUNTS:1",
            canonical_account_name="Example", normalized_account_name="example")
        old_group = CountryAccountService.ensure_account_group(account)
        self.assertEqual(old_group.country, "UNASSIGNED")
        self.commit([self.incoming(company_code="TEST")],
                    [{"source_record_id": "1", "source_account_name": "Example"}])
        membership = CountryAccountMembership.objects.get(business_account=account, active=True)
        self.assertEqual(membership.country_account.country, "CI")
        self.row.refresh_from_db()
        self.assertFalse(self.row.active)
        self.assertEqual(RevenueSourceSnapshot.objects.filter(active=True).count(), 1)

    def test_repeated_country_roundtrip_does_not_collide(self):
        account = BusinessAccount.objects.create(canonical_account_code="MININGACCOUNTS:1",
            canonical_account_name="Example", normalized_account_name="example")
        for country in ("CI", "SN", "CI", "SN", "CI"):
            account.assigned_operating_country = country
            account.save(update_fields=["assigned_operating_country"])
            group = CountryAccountService.ensure_account_group(account)
            self.assertEqual(group.country, country)
        self.assertEqual(CountryAccountMembership.objects.filter(business_account=account, active=True).count(), 1)
        names = list(CountryAccount.objects.filter(country="CI").values_list("normalized_country_account_name", flat=True))
        self.assertEqual(len(names), len(set(names)))
