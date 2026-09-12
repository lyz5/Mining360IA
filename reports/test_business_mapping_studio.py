from __future__ import annotations

import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .business_mapping_publication_service import MappingPublicationService
from .business_mapping_source_service import BusinessMappingSourceSynchronizationService
from .business_mapping_validation_service import AccountMineSiteValidationService, MappingValidationError
from .models import (
    AccountMineSiteMapping,
    AccountMineSiteMappingVersion,
    BusinessAccount,
    BusinessCompanyCodeReference,
    EquipmentFleetAnalysis,
    FleetSourceSnapshot,
    KeyAccount,
    KeyAccountMembership,
    MappingAuditLog,
    MappingIdempotencyRecord,
    MappingPublication,
    MappingSynchronizationRun,
    MineSite,
    PlatformUser,
    RevenueSourceSnapshot,
    RevenueSiteAllocationRule,
    SourceAccountRecord,
    SourceAccountFieldOverride,
)


FEATURES = {
    "ENABLE_BUSINESS_MAPPING_STUDIO": "Production",
    "ENABLE_BUSINESS_MAPPING_SUGGESTIONS": "Production",
    "ENABLE_BUSINESS_MAPPING_BULK_VALIDATION": "Production",
    "ENABLE_BUSINESS_MAPPING_REVENUE_ALLOCATION": "Production",
    "ENABLE_BUSINESS_MAPPING_PUBLICATION": "Production",
}


@override_settings(**FEATURES)
class BusinessMappingStudioTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("mapping-admin", "mapping@example.com", "password")
        self.client = Client()
        self.client.force_login(self.user)
        self.account = BusinessAccount.objects.create(
            canonical_account_code="ACC-001", canonical_account_name="Fekola Billing Company",
            normalized_account_name="fekola billing company", country="ML", created_by=self.user, updated_by=self.user,
        )
        self.site = MineSite.objects.create(
            minesite_code="SITE-FEKOLA", canonical_minesite_name="Fekola", normalized_minesite_name="fekola",
        )
        self.site_two = MineSite.objects.create(
            minesite_code="SITE-ESSAKANE", canonical_minesite_name="Essakane", normalized_minesite_name="essakane",
        )

    def payload(self, **changes):
        data = {
            "version": 0,
            "business_account_id": str(self.account.id),
            "minesite_id": str(self.site.id),
            "account_role": "Billing Account",
            "is_primary_site": True,
            "valid_from": "2026-01-01",
            "valid_to": None,
            "allocation": {"required": False},
            "evidence_ids": [],
            "comment": "Validated with Sales and Data teams.",
            "idempotency_key": "validation-001",
        }
        data.update(changes)
        return data

    def test_database_persistence_api_creates_mapping_version_and_audit(self):
        response = self.client.post(
            reverse("business-mapping-validate-new-api"),
            data=json.dumps(self.payload()), content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["database_commit_confirmed"])
        mapping_id = body["mapping"]["id"]
        mapping = AccountMineSiteMapping.objects.get(pk=mapping_id)
        self.assertEqual(mapping.relationship_status, "Validated")
        self.assertEqual(mapping.updated_by, self.user)
        self.assertEqual(AccountMineSiteMappingVersion.objects.filter(mapping=mapping).count(), 1)
        self.assertEqual(MappingAuditLog.objects.filter(entity_id=mapping_id, action="Mapping validated").count(), 1)

        reopened = self.client.get(reverse("business-mapping-published-api"))
        self.assertEqual(reopened.status_code, 200)
        self.client.logout()
        second = User.objects.create_superuser("second-admin", "second@example.com", "password")
        self.client.force_login(second)
        self.assertEqual(self.client.get(reverse("business-mapping-studio")).status_code, 200)
        self.assertTrue(AccountMineSiteMapping.objects.filter(pk=mapping_id).exists())

    def test_minimal_account_minesite_mapping_uses_governed_defaults(self):
        response = self.client.post(
            reverse("business-mapping-validate-new-api"),
            data=json.dumps({
                "business_account_id": str(self.account.id),
                "minesite_id": str(self.site.id),
                "idempotency_key": "minimal-account-site-mapping",
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        mapping = AccountMineSiteMapping.objects.get(pk=response.json()["mapping"]["id"])
        self.assertEqual(mapping.account_role, "Mapped Account")
        self.assertIsNone(mapping.valid_from)
        self.assertFalse(mapping.is_primary_site)
        self.assertFalse(mapping.allocation_required)
        self.assertEqual(mapping.notes, "")

    def test_double_click_is_idempotent(self):
        service = AccountMineSiteValidationService(self.user)
        payload = self.payload()
        first = service.validate(payload)
        second = service.validate(payload)
        self.assertEqual(first, second)
        self.assertEqual(AccountMineSiteMapping.objects.count(), 1)
        self.assertEqual(AccountMineSiteMappingVersion.objects.count(), 1)
        self.assertEqual(MappingAuditLog.objects.filter(action="Mapping validated").count(), 1)
        self.assertEqual(MappingIdempotencyRecord.objects.count(), 1)

    def test_account_detail_returns_existing_mapping_for_immediate_display(self):
        run = MappingSynchronizationRun.objects.create(status="Completed", initiated_by=self.user)
        source = SourceAccountRecord.objects.create(
            source_system="MiningAccounts", source_record_id="C001", source_account_name="Fekola Billing Company",
            normalized_account_name="fekola billing company", canonical_account=self.account,
            source_hash="source-existing", source_last_seen_at="2026-09-05T13:00:00Z", synchronization_run=run,
        )
        result = AccountMineSiteValidationService(self.user).validate(self.payload(idempotency_key="visible-existing"))
        response = self.client.get(reverse("business-mapping-account-detail-api", args=[source.id]))
        self.assertEqual(response.status_code, 200)
        mapping = response.json()["current_mappings"][0]
        self.assertEqual(mapping["id"], result["mapping"]["id"])
        self.assertEqual(mapping["minesite"]["name"], "Fekola")
        self.assertEqual(mapping["account_role"], "Billing Account")
        self.assertEqual(mapping["status"], "Validated")
        self.assertEqual(mapping["source_accounts"][0]["name"], "Fekola Billing Company")
        self.assertEqual(mapping["source_accounts"][0]["code"], "C001")

    def test_canonical_detail_aggregates_all_same_identity_source_revenue(self):
        run = MappingSynchronizationRun.objects.create(status="Completed", initiated_by=self.user)
        empty_account = BusinessAccount.objects.create(
            canonical_account_code="SNIM-23", canonical_account_name="SNIM", normalized_account_name="snim",
        )
        revenue_account = BusinessAccount.objects.create(
            canonical_account_code="SNIM-27", canonical_account_name="SNIM", normalized_account_name="snim",
        )
        first = SourceAccountRecord.objects.create(
            source_system="MiningAccounts", source_record_id="23-12577", source_account_name="SNIM",
            normalized_account_name="snim", country="MR", canonical_account=empty_account,
            source_hash="snim-23", source_last_seen_at="2026-09-05T13:00:00Z", synchronization_run=run,
        )
        SourceAccountRecord.objects.create(
            source_system="MiningAccounts", source_record_id="27-12577", source_account_name="SNIM",
            normalized_account_name="snim", country="MR", canonical_account=revenue_account,
            source_hash="snim-27", source_last_seen_at="2026-09-05T13:00:00Z", synchronization_run=run,
        )
        RevenueSourceSnapshot.objects.create(
            synchronization_run=run, source_record_id="snim-parts", source_account_code="27-12577",
            source_account_name="SNIM", division="MI", lob="PARTS", revenue_ytd_eur=53000000,
            revenue_previous_year_eur=56000000, source_hash="snim-revenue",
            source_last_seen_at="2026-09-05T13:00:00Z",
        )
        AccountMineSiteMapping.objects.create(
            business_account=revenue_account, minesite=self.site, account_role="Billing Account",
            relationship_status="Validated", valid_from="2026-01-01", created_by=self.user, updated_by=self.user,
        )

        canonical = self.client.get(
            reverse("business-mapping-account-detail-api", args=[first.id]), {"view": "canonical"}
        ).json()
        source_only = self.client.get(
            reverse("business-mapping-account-detail-api", args=[first.id]), {"view": "source"}
        ).json()
        self.assertEqual(canonical["account"]["source_record_count"], 2)
        self.assertEqual(set(canonical["account"]["source_account_codes"]), {"23-12577", "27-12577"})
        self.assertEqual(canonical["revenue_summary"]["ytd"], "53000000")
        self.assertEqual(canonical["revenue_summary"]["previous_year"], "56000000")
        self.assertEqual(canonical["revenue_summary"]["scope_label"], "Canonical Account Revenue")
        self.assertEqual(canonical["current_mappings"][0]["minesite"]["name"], "Fekola")
        self.assertIsNone(source_only["revenue_summary"]["ytd"])
        self.assertEqual(source_only["revenue_summary"]["scope_label"], "Source Record Revenue")

    def test_revenue_period_filters_totals_rankings_and_all_periods(self):
        run = MappingSynchronizationRun.objects.create(
            status="Completed", initiated_by=self.user,
            source_context_json={"revenue_period_year": 2026, "available_revenue_years": [2026, 2025, 2024, 2023]},
        )
        second_account = BusinessAccount.objects.create(
            canonical_account_code="ACC-002", canonical_account_name="Second Mining Account",
            normalized_account_name="second mining account", country="ML",
        )
        for account, code in ((self.account, "C001"), (second_account, "C002")):
            SourceAccountRecord.objects.create(
                source_system="MiningAccounts", source_record_id=code,
                source_account_name=account.canonical_account_name,
                normalized_account_name=account.normalized_account_name,
                country="ML", canonical_account=account, source_hash=f"source-{code}",
                source_last_seen_at="2026-09-05T13:00:00Z", synchronization_run=run,
            )
        values = {
            "C001": {2026: 100, 2025: 50, 2024: 300, 2023: 10},
            "C002": {2026: 200, 2025: 400, 2024: 20, 2023: 5},
        }
        for code, years in values.items():
            for year, value in years.items():
                RevenueSourceSnapshot.objects.create(
                    synchronization_run=run, source_record_id=f"{code}-{year}",
                    source_account_code=code, source_account_name=code,
                    division="MI", lob="PARTS", period_year=year,
                    revenue_ytd_eur=value, source_hash=f"revenue-{code}-{year}",
                    source_last_seen_at="2026-09-05T13:00:00Z",
                )

        overview_2024 = self.client.get(reverse("business-mapping-overview-api"), {"period": "2024"}).json()
        overview_all = self.client.get(reverse("business-mapping-overview-api"), {"period": "all"}).json()
        ranking_2024 = self.client.get(reverse("business-mapping-accounts-api"), {"view": "canonical", "period": "2024"}).json()
        ranking_2025 = self.client.get(reverse("business-mapping-accounts-api"), {"view": "canonical", "period": "2025"}).json()

        self.assertEqual(overview_2024["summary"]["unallocated_revenue_eur"], "320")
        self.assertEqual(overview_2024["source_context"]["revenue"]["label"], "2024")
        self.assertEqual(overview_all["summary"]["unallocated_revenue_eur"], "1085")
        self.assertEqual(overview_all["source_context"]["revenue"]["selected_period"], "all")
        self.assertEqual(ranking_2024["results"][0]["source_account_name"], "Fekola Billing Company")
        self.assertEqual(ranking_2025["results"][0]["source_account_name"], "Second Mining Account")

    def test_key_account_combines_canonical_accounts_revenue_and_sites(self):
        run = MappingSynchronizationRun.objects.create(status="Completed", initiated_by=self.user)
        second_account = BusinessAccount.objects.create(
            canonical_account_code="ACC-002", canonical_account_name="Corica Site Two",
            normalized_account_name="corica site two", country="ML",
        )
        for code, name, account, revenue in (
            ("CORICA-1", "Corica Site One", self.account, 120),
            ("CORICA-2", "Corica Site Two", second_account, 80),
        ):
            SourceAccountRecord.objects.create(
                source_system="MiningAccounts", source_record_id=code, source_account_name=name,
                normalized_account_name=name.casefold(), country="ML", canonical_account=account,
                source_hash=f"source-{code}", source_last_seen_at="2026-09-05T13:00:00Z", synchronization_run=run,
            )
            RevenueSourceSnapshot.objects.create(
                synchronization_run=run, source_record_id=f"revenue-{code}", source_account_code=code,
                source_account_name=name, company_code="36", operating_country="ML", division="MI", lob="PARTS", revenue_ytd_eur=revenue,
                revenue_previous_year_eur=0, source_hash=f"revenue-{code}", source_last_seen_at="2026-09-05T13:00:00Z",
            )
        AccountMineSiteMapping.objects.create(
            business_account=self.account, minesite=self.site, account_role="Billing Account",
            relationship_status="Validated", valid_from="2026-01-01", created_by=self.user, updated_by=self.user,
        )
        AccountMineSiteMapping.objects.create(
            business_account=second_account, minesite=self.site_two, account_role="Billing Account",
            relationship_status="Validated", valid_from="2026-01-01", created_by=self.user, updated_by=self.user,
        )
        created = self.client.post(
            reverse("business-mapping-key-accounts-api"), data=json.dumps({"name": "Corica Group"}),
            content_type="application/json",
        )
        self.assertEqual(created.status_code, 201)
        key_account_id = created.json()["key_account"]["id"]
        added = self.client.post(
            reverse("business-mapping-key-account-members-api", args=[key_account_id]),
            data=json.dumps({"business_account_ids": [str(self.account.id), str(second_account.id)]}),
            content_type="application/json",
        )
        self.assertEqual(added.status_code, 200)
        self.assertTrue(added.json()["database_commit_confirmed"])
        listing = self.client.get(reverse("business-mapping-key-accounts-api"), {"lob": "PARTS"}).json()["key_accounts"][0]
        self.assertEqual(listing["name"], "Corica Group")
        self.assertEqual(listing["canonical_account_count"], 2)
        self.assertEqual(listing["revenue_ytd"], "200")
        self.assertEqual([member["name"] for member in listing["members"]], ["Fekola Billing Company", "Corica Site Two"])
        self.assertEqual(set(listing["minesites"]), {"Fekola", "Essakane"})
        self.assertEqual(KeyAccountMembership.objects.filter(key_account_id=key_account_id, active=True).count(), 2)
        filtered_accounts = self.client.get(
            reverse("business-mapping-accounts-api"), {"view": "canonical", "key_account": key_account_id},
        ).json()
        unassigned_accounts = self.client.get(
            reverse("business-mapping-accounts-api"), {"view": "canonical", "key_account": "unassigned"},
        ).json()
        self.assertEqual(filtered_accounts["count"], 2)
        self.assertEqual(unassigned_accounts["count"], 0)
        self.assertEqual(filtered_accounts["filters"]["key_accounts"][0]["key_account_name"], "Corica Group")

        other = self.client.post(
            reverse("business-mapping-key-accounts-api"), data=json.dumps({"name": "Another Group"}),
            content_type="application/json",
        ).json()["key_account"]["id"]
        conflict = self.client.post(
            reverse("business-mapping-key-account-members-api", args=[other]),
            data=json.dumps({"business_account_ids": [str(self.account.id)]}), content_type="application/json",
        )
        self.assertEqual(conflict.status_code, 409)

        removed = self.client.delete(
            reverse("business-mapping-key-account-members-api", args=[key_account_id]),
            data=json.dumps({"business_account_ids": [str(second_account.id)]}), content_type="application/json",
        )
        self.assertEqual(removed.status_code, 200)
        self.assertFalse(KeyAccountMembership.objects.get(key_account_id=key_account_id, business_account=second_account).active)
        self.assertEqual(KeyAccount.objects.get(pk=key_account_id).version, 3)
        unassigned = self.client.get(reverse("business-mapping-key-accounts-api"), {"account_search": "Corica Site Two"}).json()
        self.assertEqual(unassigned["available_account_count"], 1)
        self.assertEqual(unassigned["available_accounts"][0]["name"], "Corica Site Two")

        renamed = self.client.patch(
            reverse("business-mapping-key-account-detail-api", args=[key_account_id]),
            data=json.dumps({"name": "Corica International", "version": 3}), content_type="application/json",
        )
        self.assertEqual(renamed.status_code, 200)
        self.assertEqual(renamed.json()["key_account"]["name"], "Corica International")
        stale = self.client.patch(
            reverse("business-mapping-key-account-detail-api", args=[key_account_id]),
            data=json.dumps({"name": "Stale Name", "version": 3}), content_type="application/json",
        )
        self.assertEqual(stale.status_code, 409)
        deleted = self.client.delete(
            reverse("business-mapping-key-account-detail-api", args=[key_account_id]),
            data=json.dumps({"reason": "Commercial group no longer required", "version": 4}), content_type="application/json",
        )
        self.assertEqual(deleted.status_code, 200)
        self.assertTrue(deleted.json()["database_commit_confirmed"])
        self.assertFalse(KeyAccount.objects.get(pk=key_account_id).active)
        self.assertFalse(KeyAccountMembership.objects.filter(key_account_id=key_account_id, active=True).exists())
        self.assertEqual(MappingAuditLog.objects.filter(entity_id=key_account_id, action="Key Account renamed").count(), 1)
        self.assertEqual(MappingAuditLog.objects.filter(entity_id=key_account_id, action="Key Account archived").count(), 1)

    def test_remove_mapping_archives_and_preserves_published_history(self):
        validated = AccountMineSiteValidationService(self.user).validate(self.payload(idempotency_key="archive-source"))
        mapping_id = validated["mapping"]["id"]
        publication = MappingPublicationService(self.user).publish("Before governed removal")
        payload = {"version": validated["mapping"]["version"], "reason": "Relationship corrected by Data Steward", "idempotency_key": "archive-once"}
        response = self.client.post(
            reverse("business-mapping-archive-api", args=[mapping_id]),
            data=json.dumps(payload), content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["database_commit_confirmed"])
        self.assertTrue(response.json()["published_snapshot_unchanged"])
        mapping = AccountMineSiteMapping.objects.get(pk=mapping_id)
        self.assertFalse(mapping.active)
        self.assertEqual(mapping.relationship_status, "Archived")
        self.assertEqual(AccountMineSiteMappingVersion.objects.filter(mapping=mapping).count(), 2)
        self.assertTrue(MappingAuditLog.objects.filter(entity_id=mapping_id, action="Mapping archived").exists())
        publication.refresh_from_db()
        self.assertEqual(len(publication.snapshot_json["mappings"]), 1)

        duplicate = self.client.post(
            reverse("business-mapping-archive-api", args=[mapping_id]),
            data=json.dumps(payload), content_type="application/json",
        )
        self.assertEqual(duplicate.status_code, 200)
        self.assertEqual(AccountMineSiteMappingVersion.objects.filter(mapping=mapping).count(), 2)
        self.assertEqual(MappingAuditLog.objects.filter(entity_id=mapping_id, action="Mapping archived").count(), 1)

    def test_stale_version_returns_conflict_without_overwrite(self):
        service = AccountMineSiteValidationService(self.user)
        draft = service.save_draft(self.payload(idempotency_key="draft-001"))
        mapping_id = draft["mapping"]["id"]
        service.validate(self.payload(mapping_id=mapping_id, version=1, idempotency_key="validate-current"), mapping_id)
        with self.assertRaises(MappingValidationError) as caught:
            service.validate(self.payload(mapping_id=mapping_id, version=1, account_role="Procurement Account", idempotency_key="validate-stale"), mapping_id)
        self.assertEqual(caught.exception.status, 409)
        mapping = AccountMineSiteMapping.objects.get(pk=mapping_id)
        self.assertEqual(mapping.account_role, "Billing Account")
        self.assertEqual(mapping.current_version, 2)

    def test_many_to_many_roles_are_valid(self):
        service = AccountMineSiteValidationService(self.user)
        service.validate(self.payload(idempotency_key="multi-1"))
        service.validate(self.payload(minesite_id=str(self.site_two.id), account_role="Procurement Account", is_primary_site=False, idempotency_key="multi-2"))
        third_site = MineSite.objects.create(minesite_code="SITE-THIRD", canonical_minesite_name="Third Mine", normalized_minesite_name="third mine")
        service.validate(self.payload(minesite_id=str(third_site.id), account_role="Parent Group", is_primary_site=False, idempotency_key="multi-3"))
        self.assertEqual(AccountMineSiteMapping.objects.filter(business_account=self.account, relationship_status="Validated").count(), 3)

    def test_revenue_allocation_60_40_and_over_100_blocked(self):
        service = AccountMineSiteValidationService(self.user)
        service.validate(self.payload(idempotency_key="alloc-60", allocation={"required": True, "percentage": 60, "lob": "PARTS"}))
        service.validate(self.payload(idempotency_key="alloc-40", minesite_id=str(self.site_two.id), account_role="Procurement Account", allocation={"required": True, "percentage": 40, "lob": "PARTS"}))
        self.assertEqual(RevenueSiteAllocationRule.objects.filter(business_account=self.account, lob="PARTS").count(), 2)
        self.assertEqual(sum(rule.allocation_percentage for rule in RevenueSiteAllocationRule.objects.filter(business_account=self.account, lob="PARTS")), 100)

        other = BusinessAccount.objects.create(canonical_account_code="ACC-002", canonical_account_name="Other", normalized_account_name="other")
        service.validate(self.payload(business_account_id=str(other.id), idempotency_key="alloc-70", allocation={"required": True, "percentage": 70, "lob": "PRIME"}))
        with self.assertRaises(MappingValidationError) as caught:
            service.validate(self.payload(business_account_id=str(other.id), minesite_id=str(self.site_two.id), account_role="Procurement Account", idempotency_key="alloc-50", allocation={"required": True, "percentage": 50, "lob": "PRIME"}))
        self.assertEqual(caught.exception.code, "ALLOCATION_EXCEEDS_100")
        self.assertEqual(RevenueSiteAllocationRule.objects.filter(business_account=other, lob="PRIME").count(), 1)

    def test_no_minesite_required_is_governed_and_audited(self):
        result = AccountMineSiteValidationService(self.user).validate(
            self.payload(minesite_id=None, account_role="Head Office", no_site_reason="Regional Office", idempotency_key="no-site"),
            no_site_required=True,
        )
        mapping = AccountMineSiteMapping.objects.get(pk=result["mapping"]["id"])
        self.assertIsNone(mapping.minesite_id)
        self.assertEqual(mapping.relationship_status, "No MineSite Required")
        self.assertEqual(mapping.no_site_reason, "Regional Office")
        self.assertTrue(MappingAuditLog.objects.filter(entity_id=str(mapping.id), action="No MineSite Required decision").exists())

    def test_publication_and_rollback_are_immutable_versions(self):
        AccountMineSiteValidationService(self.user).validate(self.payload())
        service = MappingPublicationService(self.user)
        first = service.publish("Initial publication")
        rollback = service.rollback(first, "Return to the approved snapshot")
        self.assertEqual([first.version, rollback.version], [1, 2])
        self.assertEqual(MappingPublication.objects.count(), 2)
        self.assertEqual(rollback.rollback_of, first)
        published = self.client.get(reverse("business-mapping-published-api")).json()
        self.assertEqual(published["publication_version"], 2)
        self.assertEqual(len(published["results"]), 1)

    def test_source_sync_preserves_previous_snapshot(self):
        first_run = MappingSynchronizationRun.objects.create(status="Queued", initiated_by=self.user)
        service = BusinessMappingSourceSynchronizationService(self.user)
        with patch.object(service, "fetch_equipment_analysis_rows", return_value=([{
            "Site": "Fekola", "Equipment": "DT001", "Model": "777", "ParentProductGroup": "OFF-HIGHWAY TRUCK",
            "SN": "SN001", "Brand": "CAT", "EquipID": "101", "Status": "-1", "SMU.SMU": "1234.5",
        }], "equipment-model-id")):
            with patch.object(service, "fetch_source_rows", return_value=(
                [{"source_record_id": "C001", "source_account_name": "Fekola Billing", "country_code": "ML"}],
                [{"customer": "Fekola Billing", "minesite": "Fekola", "equipment": "DT001", "serial_number": "SN001", "model": "777"}],
                [
                    {"source_account_code": "C001", "source_account_name": "Fekola Billing", "division": "MI", "lob": "PARTS", "period_year": 2026, "revenue_ytd_eur": 1000, "revenue_previous_year_eur": 800, "invoice_count": 2},
                    {"source_account_code": "C001", "source_account_name": "Fekola Billing", "division": "MI", "lob": "PARTS", "distribution_channel": "Interco", "period_year": 2026, "revenue_ytd_eur": 5000, "revenue_previous_year_eur": 4000, "invoice_count": 1},
                    {"source_account_code": "C001", "source_account_name": "Fekola Billing", "division": "TP", "lob": "PARTS", "period_year": 2026, "revenue_ytd_eur": 9000, "revenue_previous_year_eur": 7000, "invoice_count": 3},
                ],
            )):
                service.process(first_run)
            second_run = MappingSynchronizationRun.objects.create(status="Queued", initiated_by=self.user)
            with patch.object(service, "fetch_source_rows", return_value=(
                [{"source_record_id": "C001", "source_account_name": "Fekola Billing", "country_code": "ML"}],
                [{"customer": "Fekola Billing", "minesite": "Fekola", "equipment": "DT002", "serial_number": "SN002", "model": "777"}],
                [],
            )):
                service.process(second_run)
        self.assertEqual(FleetSourceSnapshot.objects.count(), 2)
        self.assertEqual(FleetSourceSnapshot.objects.filter(active=True).count(), 1)
        self.assertTrue(SourceAccountRecord.objects.filter(source_system="MiningAccounts", source_record_id="C001", active=True).exists())
        self.assertEqual(first_run.source_context_json["revenue_period_year"], 2026)
        self.assertEqual(first_run.source_context_json["revenue_division"], "MI")
        self.assertEqual(first_run.source_context_json["revenue_lobs"], ["PRIME", "PARTS", "SERVICE", "RENTAL"])
        self.assertEqual(RevenueSourceSnapshot.objects.count(), 1)
        self.assertEqual(RevenueSourceSnapshot.objects.get().division, "MI")
        self.assertEqual(RevenueSourceSnapshot.objects.get().revenue_ytd_eur, 1000)
        self.assertEqual(EquipmentFleetAnalysis.objects.count(), 2)
        self.assertEqual(EquipmentFleetAnalysis.objects.filter(active=True).count(), 1)
        equipment = EquipmentFleetAnalysis.objects.filter(active=True).get()
        self.assertEqual(equipment.source_table, "EquipmentList_MiningProd")
        self.assertEqual(equipment.equipment_id, "101")
        self.assertEqual(str(equipment.smu), "1234.50")

    def test_governed_country_override_survives_source_synchronization(self):
        run = MappingSynchronizationRun.objects.create(status="Running", initiated_by=self.user)
        self.assertTrue(SourceAccountFieldOverride.objects.filter(
            source_system="MiningAccounts", source_record_id="23-12278", field_name="country",
            corrected_value="GN", active=True,
        ).exists())
        service = BusinessMappingSourceSynchronizationService(self.user)
        service._source_warnings = []
        service._commit_snapshot(
            run,
            account_rows=[{"source_record_id": "23-12278", "source_account_name": "CBG CONTRAT MARC", "country_code": "US"}],
            fleet_rows=[], revenue_rows=[], equipment_rows=[], equipment_semantic_model_id="",
        )
        record = SourceAccountRecord.objects.get(source_system="MiningAccounts", source_record_id="23-12278")
        self.assertEqual(record.country, "GN")
        self.assertEqual(record.canonical_account.country, "GN")
        self.assertEqual(record.source_payload_json["source_country"], "US")
        self.assertTrue(record.source_payload_json["country_override_applied"])

    def test_source_sync_updates_revenue_when_legacy_fleet_table_is_unavailable(self):
        previous_run = MappingSynchronizationRun.objects.create(status="Completed", initiated_by=self.user)
        previous_fleet = FleetSourceSnapshot.objects.create(
            synchronization_run=previous_run,
            source_record_id="legacy-fleet-row",
            customer="Fekola Billing",
            minesite_name="Fekola",
            source_hash="legacy-hash",
            source_last_seen_at="2026-09-04T10:30:00Z",
        )
        run = MappingSynchronizationRun.objects.create(status="Queued", initiated_by=self.user)
        service = BusinessMappingSourceSynchronizationService(self.user)

        def source_rows():
            service._source_warnings.append({
                "code": "LEGACY_FLEET_SOURCE_UNAVAILABLE",
                "message": "Cannot find table Fleet.",
            })
            return (
                [{"source_record_id": "C001", "source_account_name": "Fekola Billing", "country_code": "ML"}],
                None,
                [{
                    "source_account_code": "C001", "source_account_name": "Fekola Billing",
                    "division": "MI", "lob": "PARTS", "period_year": 2026,
                    "revenue_ytd_eur": 175700000, "revenue_previous_year_eur": 100,
                }],
            )

        with patch.object(service, "fetch_source_rows", side_effect=source_rows), patch.object(
            service,
            "fetch_equipment_analysis_rows",
            return_value=([], "equipment-model-id"),
        ):
            service.process(run)

        run.refresh_from_db()
        previous_fleet.refresh_from_db()
        self.assertEqual(run.status, "Completed")
        self.assertEqual(run.warnings_json[0]["code"], "LEGACY_FLEET_SOURCE_UNAVAILABLE")
        self.assertTrue(previous_fleet.active)
        self.assertFalse(run.source_context_json["legacy_fleet_snapshot_updated"])
        self.assertEqual(
            RevenueSourceSnapshot.objects.filter(active=True).get().revenue_ytd_eur,
            175700000,
        )

    @patch("reports.business_mapping_views.enqueue_business_mapping_sync")
    def test_synchronization_api_exposes_progress_and_reuses_active_run(self, enqueue_mock):
        started = self.client.post(reverse("business-mapping-synchronization-api"), data="{}", content_type="application/json")
        self.assertEqual(started.status_code, 202)
        run = started.json()["run"]
        self.assertEqual(run["status"], "Queued")
        self.assertEqual(run["progress_percent"], 0)
        self.assertEqual(run["stage"], "Waiting for the synchronization worker")
        enqueue_mock.assert_called_once()

        latest = self.client.get(reverse("business-mapping-synchronization-api"))
        self.assertEqual(latest.status_code, 200)
        self.assertEqual(latest.json()["run"]["id"], run["id"])

        status = self.client.get(reverse("business-mapping-synchronization-status-api", args=[run["id"]]))
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["run"]["progress_percent"], 0)

        duplicate = self.client.post(reverse("business-mapping-synchronization-api"), data="{}", content_type="application/json")
        self.assertEqual(duplicate.status_code, 200)
        self.assertTrue(duplicate.json()["reused"])
        self.assertEqual(duplicate.json()["run"]["id"], run["id"])

    def test_synchronization_progress_is_persisted_and_exposed(self):
        run = MappingSynchronizationRun.objects.create(
            status="Running",
            progress_percent=60,
            stage_code="equipment",
            stage_label="Retrieving EquipmentList_MiningProd Fleet",
            heartbeat_at=timezone.now(),
            initiated_by=self.user,
        )
        response = self.client.get(reverse("business-mapping-synchronization-status-api", args=[run.id]))
        self.assertEqual(response.status_code, 200)
        payload = response.json()["run"]
        self.assertEqual(payload["progress_percent"], 60)
        self.assertEqual(payload["stage"], "Retrieving EquipmentList_MiningProd Fleet")

    def test_overview_exposes_revenue_fleet_and_mapping_periods(self):
        run = MappingSynchronizationRun.objects.create(
            status="Completed",
            source_context_json={
                "revenue_period_kind": "YTD", "revenue_period_year": 2026, "previous_year": 2025,
                "snapshot_completed_at": "2026-09-04T10:30:00+00:00",
                "fleet_snapshot_kind": "current_source_snapshot",
            },
        )
        RevenueSourceSnapshot.objects.create(
            synchronization_run=run, source_record_id="period-row", source_account_code="ACC-001",
            division="MI", lob="PRIME", revenue_ytd_eur=100, revenue_previous_year_eur=80,
            source_hash="hash", source_last_seen_at="2026-09-04T10:30:00Z",
        )
        RevenueSourceSnapshot.objects.create(
            synchronization_run=run, source_record_id="non-mining-row", source_account_code="ACC-001",
            division="TP", lob="PRIME", revenue_ytd_eur=900,
            source_hash="hash-2", source_last_seen_at="2026-09-04T10:30:00Z",
        )
        response = self.client.get(reverse("business-mapping-overview-api"))
        self.assertEqual(response.status_code, 200)
        context = response.json()["source_context"]
        self.assertEqual(context["revenue"]["label"], "YTD 2026")
        self.assertEqual(context["revenue"]["previous_year"], 2025)
        self.assertEqual(context["fleet"]["snapshot_at"], "2026-09-04T10:30:00+00:00")
        self.assertEqual(context["mappings"]["kind"], "current_database_state")
        self.assertEqual(context["revenue"]["scope"], "Mining")
        self.assertEqual(context["revenue"]["categories"], ["Machine", "Parts", "Service", "Rental"])
        breakdown = {item["code"]: item["value"] for item in response.json()["revenue_breakdown"]}
        self.assertEqual(breakdown, {"PRIME": "100", "PARTS": "0", "SERVICE": "0", "RENTAL": "0"})
        self.assertEqual(response.json()["summary"]["total_revenue_eur"], "100")
        self.assertEqual(response.json()["summary"]["unallocated_revenue_eur"], "100")
        parts_response = self.client.get(reverse("business-mapping-overview-api"), {"lob": "PARTS"}).json()
        self.assertEqual(parts_response["source_context"]["revenue"]["selected_category"], "Parts")
        self.assertEqual(parts_response["summary"]["unallocated_revenue_eur"], "0")

    def test_standard_user_is_blocked_by_backend(self):
        standard = User.objects.create_user("standard", "standard@example.com", "password")
        self.client.force_login(standard)
        self.assertIn(self.client.get(reverse("business-mapping-studio")).status_code, {302, 403})
        response = self.client.post(reverse("business-mapping-validate-new-api"), data=json.dumps(self.payload()), content_type="application/json", HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 403)

    def test_authorized_minesite_selector_respects_scope(self):
        scoped = User.objects.create_user("scoped", "scoped@example.com", "password")
        PlatformUser.objects.create(
            azure_ad_id="scoped-id", user_principal_name="scoped@example.com", display_name="Scoped User",
            django_user=scoped, can_access_data=True, business_performance_scope={"minesites": ["Fekola"]},
        )
        from django.contrib.auth.models import Permission
        scoped.user_permissions.add(Permission.objects.get(codename="view_business_mapping"))
        self.client.force_login(scoped)
        response = self.client.get(reverse("business-mapping-minesites-api"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["name"] for item in response.json()["results"]], ["Fekola"])

    def test_equipment_analysis_api_uses_equipment_list_and_respects_site_scope(self):
        run = MappingSynchronizationRun.objects.create(status="Completed")
        for position, (site, smu) in enumerate((("Fekola", None), ("Essakane", 4500))):
            EquipmentFleetAnalysis.objects.create(
                synchronization_run=run,
                source_record_id=f"equipment-{position}",
                semantic_model_id="equipment-model-id",
                equipment_id=str(position + 1),
                site=site,
                normalized_site=site.casefold(),
                equipment=f"DT00{position + 1}",
                model="777",
                serial_number=f"SN00{position + 1}",
                equipment_family="OFF-HIGHWAY TRUCK",
                brand="CAT",
                source_status="-1",
                smu=smu,
                source_hash=f"hash-{position}",
                source_last_seen_at="2026-09-04T12:30:00Z",
            )
        scoped = User.objects.create_user("fleet-reader", "fleet@example.com", "password")
        PlatformUser.objects.create(
            azure_ad_id="fleet-reader-id", user_principal_name="fleet@example.com", display_name="Fleet Reader",
            django_user=scoped, can_access_data=True, business_performance_scope={"minesites": ["Fekola"]},
        )
        from django.contrib.auth.models import Permission
        scoped.user_permissions.add(Permission.objects.get(codename="view_business_mapping"))
        self.client.force_login(scoped)
        response = self.client.get(reverse("business-mapping-equipment-analysis-api"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["source"]["table"], "EquipmentList_MiningProd")
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["site"], "Fekola")
        self.assertIsNone(response.json()["results"][0]["smu"])

    def test_account_queue_sorts_by_mining_revenue_before_pagination(self):
        run = MappingSynchronizationRun.objects.create(status="Completed")
        for code, name, country in (("LOW", "Low Revenue", "BF"), ("HIGH", "High Revenue", "ML")):
            account = BusinessAccount.objects.create(
                canonical_account_code=code,
                canonical_account_name=name,
                normalized_account_name=name.casefold(),
            )
            SourceAccountRecord.objects.create(
                source_system="MiningAccounts",
                source_record_id=code,
                source_account_name=name,
                normalized_account_name=name.casefold(),
                country=country,
                canonical_account=account,
                source_hash=f"hash-{code}",
                source_last_seen_at="2026-09-04T12:30:00Z",
                synchronization_run=run,
            )
        RevenueSourceSnapshot.objects.create(
            synchronization_run=run, source_record_id="low-mi", source_account_code="LOW",
            division="MI", lob="PARTS", operating_country="BF", company_code="31", revenue_ytd_eur=100,
            source_hash="low-mi", source_last_seen_at="2026-09-04T12:30:00Z",
        )
        RevenueSourceSnapshot.objects.create(
            synchronization_run=run, source_record_id="low-non-mining", source_account_code="LOW",
            division="TP", lob="PARTS", revenue_ytd_eur=10000,
            source_hash="low-tp", source_last_seen_at="2026-09-04T12:30:00Z",
        )
        RevenueSourceSnapshot.objects.create(
            synchronization_run=run, source_record_id="high-mi", source_account_code="HIGH",
            division="MI", lob="PRIME", operating_country="ML", company_code="36", revenue_ytd_eur=200,
            source_hash="high-mi", source_last_seen_at="2026-09-04T12:30:00Z",
        )
        descending = self.client.get(reverse("business-mapping-accounts-api"), {"sort": "revenue_desc"}).json()
        default_order = self.client.get(reverse("business-mapping-accounts-api")).json()
        canonical_default = self.client.get(reverse("business-mapping-accounts-api"), {"view": "canonical"}).json()
        searched_source = self.client.get(reverse("business-mapping-accounts-api"), {"search": "LOW"}).json()
        searched_canonical = self.client.get(reverse("business-mapping-accounts-api"), {"view": "canonical", "search": "LOW"}).json()
        ascending = self.client.get(reverse("business-mapping-accounts-api"), {"sort": "revenue_asc"}).json()
        parts_only = self.client.get(reverse("business-mapping-accounts-api"), {"sort": "revenue_desc", "lob": "PARTS"}).json()
        burkina_faso = self.client.get(reverse("business-mapping-accounts-api"), {"country": "BF"}).json()
        burkina_overview = self.client.get(reverse("business-mapping-overview-api"), {"country": "BF"}).json()
        country_not_validated = self.client.get(reverse("business-mapping-accounts-api"), {"country": "UNASSIGNED"}).json()
        country_not_validated_overview = self.client.get(reverse("business-mapping-overview-api"), {"country": "UNASSIGNED"}).json()
        self.assertEqual([row["source_account_code"] for row in descending["results"]], ["HIGH", "LOW"])
        self.assertEqual([row["revenue_rank"] for row in descending["results"]], [1, 2])
        self.assertEqual([row["source_account_code"] for row in default_order["results"]], ["HIGH", "LOW"])
        self.assertEqual([row["source_account_code"] for row in canonical_default["results"]], ["HIGH", "LOW"])
        self.assertEqual([row["revenue_rank"] for row in canonical_default["results"]], [1, 2])
        self.assertEqual(searched_source["results"][0]["revenue_rank"], 2)
        self.assertEqual(searched_canonical["results"][0]["revenue_rank"], 2)
        self.assertEqual([row["source_account_code"] for row in ascending["results"]], ["LOW", "HIGH"])
        self.assertEqual([row["source_account_code"] for row in parts_only["results"]], ["LOW", "HIGH"])
        self.assertEqual(descending["results"][0]["revenue_ytd"], "200")
        self.assertEqual(parts_only["results"][0]["revenue_ytd"], "100")
        self.assertEqual(
            [item["code"] for item in descending["filters"]["countries"]],
            ["UNASSIGNED", "SN", "CI", "GN", "ML", "BF", "NE", "BJ", "TG", "MR", "FR", "CM", "GW", "MU"],
        )
        self.assertEqual([row["source_account_code"] for row in burkina_faso["results"]], ["LOW"])
        self.assertEqual(burkina_overview["source_context"]["business_scope"]["country"], "BF")
        self.assertEqual(burkina_overview["summary"]["total_accounts"], 1)
        self.assertEqual(burkina_overview["summary"]["unallocated_revenue_eur"], "100")
        self.assertEqual([row["source_account_code"] for row in country_not_validated["results"]], ["HIGH", "LOW"])
        self.assertEqual(country_not_validated_overview["source_context"]["business_scope"]["country"], "UNASSIGNED")
        self.assertEqual(country_not_validated_overview["summary"]["total_accounts"], 2)
        self.assertEqual(country_not_validated_overview["summary"]["total_revenue_eur"], "300")

    def test_operating_country_is_distinct_from_customer_origin(self):
        run = MappingSynchronizationRun.objects.create(status="Completed")
        account = BusinessAccount.objects.create(
            canonical_account_code="CAN-GN", canonical_account_name="Canadian Mining Customer",
            normalized_account_name="canadian mining customer", country="CA", origin_country="CA",
        )
        source = SourceAccountRecord.objects.create(
            source_system="MiningAccounts", source_record_id="34-CAN-GN",
            source_account_name="Canadian Mining Customer", normalized_account_name="canadian mining customer",
            country="CA", origin_country="CA", operating_countries_json=["GN"], canonical_account=account,
            source_hash="can-gn", source_last_seen_at="2026-09-05T13:00:00Z", synchronization_run=run,
        )
        RevenueSourceSnapshot.objects.create(
            synchronization_run=run, source_record_id="can-gn-parts", source_account_code=source.source_record_id,
            company_code="34", operating_country="GN", division="MI", lob="PARTS", revenue_ytd_eur=500,
            source_hash="can-gn-revenue", source_last_seen_at="2026-09-05T13:00:00Z",
        )
        guinea = self.client.get(reverse("business-mapping-accounts-api"), {"country": "GN"}).json()
        self.assertIn("34-CAN-GN", [item["source_account_code"] for item in guinea["results"]])
        self.assertNotIn("CA", [item["code"] for item in guinea["filters"]["countries"]])

    def test_canonical_operating_country_assignment_controls_global_filter_and_revenue(self):
        run = MappingSynchronizationRun.objects.create(status="Completed", initiated_by=self.user)
        source = SourceAccountRecord.objects.create(
            source_system="MiningAccounts", source_record_id="27-SNIM", source_account_name="SNIM",
            normalized_account_name="snim", country="MR", origin_country="MR",
            operating_countries_json=["FR"], canonical_account=self.account,
            source_hash="snim-country", source_last_seen_at="2026-09-05T13:00:00Z", synchronization_run=run,
        )
        RevenueSourceSnapshot.objects.create(
            synchronization_run=run, source_record_id="snim-fr-parts", source_account_code=source.source_record_id,
            company_code="27", operating_country="FR", division="MI", lob="PARTS", period_year=2026,
            revenue_ytd_eur=53000000, source_hash="snim-fr-revenue",
            source_last_seen_at="2026-09-05T13:00:00Z",
        )
        endpoint = reverse("business-mapping-canonical-account-operating-country-api", args=[self.account.id])
        assigned = self.client.post(endpoint, data=json.dumps({"country": "MR"}), content_type="application/json")
        self.assertEqual(assigned.status_code, 200, assigned.content)
        self.assertTrue(assigned.json()["database_commit_confirmed"])
        self.account.refresh_from_db()
        self.assertEqual(self.account.assigned_operating_country, "MR")
        self.assertEqual(self.account.operating_country_assigned_by, self.user)

        mauritania = self.client.get(reverse("business-mapping-accounts-api"), {"view": "canonical", "country": "MR"}).json()
        france = self.client.get(reverse("business-mapping-accounts-api"), {"view": "canonical", "country": "FR"}).json()
        mauritania_overview = self.client.get(reverse("business-mapping-overview-api"), {"country": "MR"}).json()
        self.assertEqual(mauritania["results"][0]["assigned_operating_countries"], ["MR"])
        self.assertEqual(mauritania["results"][0]["revenue_ytd"], "53000000")
        self.assertEqual(france["count"], 0)
        self.assertEqual(mauritania_overview["summary"]["total_revenue_eur"], "53000000")
        self.assertEqual(MappingAuditLog.objects.filter(action="Canonical Account operating country assigned").count(), 1)

        cleared = self.client.delete(endpoint, data="{}", content_type="application/json")
        self.assertEqual(cleared.status_code, 200)
        self.account.refresh_from_db()
        self.assertEqual(self.account.assigned_operating_country, "")
        restored_france = self.client.get(reverse("business-mapping-accounts-api"), {"view": "canonical", "country": "FR"}).json()
        self.assertEqual(restored_france["count"], 1)
        self.assertEqual(MappingAuditLog.objects.filter(action="Canonical Account operating country cleared").count(), 1)

    def test_company_code_reference_classifies_and_labels_source_accounts(self):
        self.assertEqual(BusinessCompanyCodeReference.objects.count(), 29)
        self.assertEqual(
            BusinessCompanyCodeReference.objects.get(company_code="33").operating_country_code,
            "GN",
        )
        self.assertEqual(
            BusinessCompanyCodeReference.objects.get(company_code="38").operating_country_code,
            "MU",
        )
        run = MappingSynchronizationRun.objects.create(status="Running", initiated_by=self.user)
        service = BusinessMappingSourceSynchronizationService(self.user)
        service._source_warnings = []
        service._commit_snapshot(
            run,
            account_rows=[{
                "source_record_id": "33-10001",
                "source_account_name": "Guinea Mining Customer",
                "country_code": "CA",
            }],
            fleet_rows=[],
            revenue_rows=[{
                "source_account_code": "33-10001",
                "source_account_name": "Guinea Mining Customer",
                "company_code": "33",
                "division": "MI",
                "lob": "PARTS",
                "period_year": 2026,
                "revenue_ytd_eur": 100,
            }],
            equipment_rows=[],
            equipment_semantic_model_id="",
        )
        source = SourceAccountRecord.objects.get(source_record_id="33-10001")
        revenue = RevenueSourceSnapshot.objects.get(source_account_code="33-10001")
        self.assertEqual(source.origin_country, "CA")
        self.assertEqual(source.operating_countries_json, ["GN"])
        self.assertEqual(
            source.source_payload_json["revenue_company_name_values"],
            ["NEEMBA MINING GUINEE"],
        )
        self.assertEqual(revenue.operating_country, "GN")
        queue = self.client.get(
            reverse("business-mapping-accounts-api"),
            {"view": "canonical", "search": "33-10001"},
        ).json()
        self.assertEqual(queue["results"][0]["company_code"], "33")
        self.assertEqual(queue["results"][0]["company_name"], "NEEMBA MINING GUINEE")

    def test_canonical_account_rename_preserves_previous_name_as_searchable_alias(self):
        run = MappingSynchronizationRun.objects.create(status="Completed", initiated_by=self.user)
        SourceAccountRecord.objects.create(
            source_system="MiningAccounts",
            source_record_id="ACC-001",
            source_account_name=self.account.canonical_account_name,
            normalized_account_name=self.account.normalized_account_name,
            country="ML",
            operating_countries_json=["ML"],
            canonical_account=self.account,
            source_hash="canonical-alias-source",
            source_last_seen_at="2026-09-05T13:00:00Z",
            synchronization_run=run,
        )
        response = self.client.post(
            reverse("business-mapping-canonical-account-aliases-api", args=[self.account.id]),
            data=json.dumps({"alias": "Fekola Mining Account"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["database_commit_confirmed"])
        self.assertEqual(response.json()["canonical_account"]["name"], "Fekola Mining Account")
        alias_id = response.json()["alias"]["id"]
        self.account.refresh_from_db()
        self.assertEqual(self.account.canonical_account_name, "Fekola Mining Account")
        searched_new_name = self.client.get(reverse("business-mapping-accounts-api"), {"view": "canonical", "search": "Fekola Mining Account"}).json()
        searched_previous_name = self.client.get(reverse("business-mapping-accounts-api"), {"view": "canonical", "search": "Fekola Billing Company"}).json()
        self.assertEqual(searched_new_name["count"], 1)
        self.assertEqual(searched_new_name["results"][0]["source_account_name"], "Fekola Mining Account")
        self.assertEqual(searched_previous_name["count"], 1)
        self.assertIn("Fekola Billing Company", searched_previous_name["results"][0]["aliases"])
        removed = self.client.delete(
            reverse("business-mapping-canonical-account-aliases-api", args=[self.account.id]),
            data=json.dumps({"alias_id": alias_id}), content_type="application/json",
        )
        self.assertEqual(removed.status_code, 200)
        self.assertEqual(removed.json()["aliases"], [])
        self.assertEqual(MappingAuditLog.objects.filter(action="Canonical Account renamed").count(), 1)
        self.assertEqual(MappingAuditLog.objects.filter(action="Canonical Account alias removed").count(), 1)

    def test_backend_blocks_validation_outside_minesite_scope(self):
        from django.contrib.auth.models import Permission

        scoped = User.objects.create_user("validator", "validator@example.com", "password")
        PlatformUser.objects.create(
            azure_ad_id="validator-id", user_principal_name="validator@example.com", display_name="Validator",
            django_user=scoped, can_access_data=True, business_performance_scope={"minesites": ["Fekola"]},
        )
        scoped.user_permissions.add(
            Permission.objects.get(codename="view_business_mapping"),
            Permission.objects.get(codename="validate_business_mapping"),
        )
        with self.assertRaises(MappingValidationError) as caught:
            AccountMineSiteValidationService(scoped).validate(
                self.payload(minesite_id=str(self.site_two.id), idempotency_key="restricted-site")
            )
        self.assertEqual(caught.exception.status, 403)
        self.assertEqual(AccountMineSiteMapping.objects.count(), 0)

    def test_audit_failure_rolls_back_entire_validation(self):
        with patch("reports.business_mapping_validation_service.MappingAuditLog.objects.create", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaises(RuntimeError):
                AccountMineSiteValidationService(self.user).validate(self.payload(idempotency_key="audit-failure"))
        self.assertEqual(AccountMineSiteMapping.objects.count(), 0)
        self.assertEqual(AccountMineSiteMappingVersion.objects.count(), 0)
        self.assertEqual(MappingIdempotencyRecord.objects.count(), 0)
