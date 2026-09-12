from __future__ import annotations

import json
from datetime import date

from django.contrib.auth.models import Permission, User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .business_mapping_publication_service import MappingPublicationService
from .business_review_snapshot_service import BusinessReviewSnapshotService
from .models import (
    AccountMineSiteMapping,
    BusinessAccount,
    BusinessPortfolioThresholdRule,
    BusinessReviewAction,
    BusinessReviewSnapshot,
    EquipmentFleetAnalysis,
    MappingAuditLog,
    MappingSynchronizationRun,
    MineSite,
    RevenueSourceSnapshot,
    SourceAccountRecord,
)


FEATURES = {
    "ENABLE_BUSINESS_MAPPING_STUDIO": "Production",
    "ENABLE_BUSINESS_MAPPING_PUBLICATION": "Production",
    "ENABLE_BUSINESS_REVIEW": "Production",
    "ENABLE_BUSINESS_REVIEW_PORTFOLIO": "Production",
    "ENABLE_BUSINESS_OPPORTUNITY_ENGINE": "Production",
    "ENABLE_BUSINESS_RISK_ENGINE": "Production",
    "ENABLE_BUSINESS_REVIEW_ACTIONS": "Production",
}


@override_settings(**FEATURES)
class BusinessReviewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("review-admin", "review-admin@example.com", "password")
        self.client = Client()
        self.client.force_login(self.admin)
        self.run = MappingSynchronizationRun.objects.create(
            status="Completed",
            initiated_by=self.admin,
            completed_at="2026-09-05T13:00:00Z",
            source_context_json={"revenue_period_kind": "YTD", "revenue_period_year": 2026},
        )
        self.account = BusinessAccount.objects.create(
            canonical_account_code="ACC-FEKOLA",
            canonical_account_name="Fekola Account",
            normalized_account_name="fekola account",
            country="ML",
            created_by=self.admin,
        )
        self.source = SourceAccountRecord.objects.create(
            source_system="MiningAccounts", source_record_id="C001", source_account_name="Fekola Account",
            normalized_account_name="fekola account", country="ML", canonical_account=self.account,
            source_hash="source-hash", source_last_seen_at="2026-09-05T13:00:00Z", synchronization_run=self.run,
        )
        self.site = MineSite.objects.create(
            minesite_code="FEKOLA", canonical_minesite_name="Fekola", normalized_minesite_name="fekola", country="ML",
        )
        RevenueSourceSnapshot.objects.create(
            synchronization_run=self.run, source_record_id="revenue-1", source_account_code="C001",
            source_account_name="Fekola Account", division="MI", lob="PARTS",
            revenue_ytd_eur=1000, revenue_previous_year_eur=800,
            source_hash="revenue-hash", source_last_seen_at="2026-09-05T13:00:00Z",
        )
        EquipmentFleetAnalysis.objects.create(
            synchronization_run=self.run, source_record_id="fleet-1", semantic_model_id="equipment-model",
            equipment_id="1", site="Fekola", normalized_site="fekola", equipment="DT001", model="777",
            serial_number="SN001", source_hash="fleet-hash", source_last_seen_at="2026-09-05T13:00:00Z",
        )

    def publish(self):
        AccountMineSiteMapping.objects.create(
            business_account=self.account, minesite=self.site, account_role="Billing Account",
            relationship_status="Validated", valid_from=date(2026, 1, 1), created_by=self.admin, updated_by=self.admin,
        )
        return MappingPublicationService(self.admin).publish("Business Review test")

    def test_no_publication_returns_controlled_not_ready_state(self):
        response = self.client.get(reverse("business-review-overview-api"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["ready"])
        self.assertEqual(response.json()["status"], "NOT_READY")

    def test_published_snapshot_uses_frozen_source_keys_and_excludes_later_draft(self):
        publication = self.publish()
        self.assertEqual(publication.snapshot_json["mappings"][0]["source_account_codes"], ["C001"])
        draft_account = BusinessAccount.objects.create(
            canonical_account_code="ACC-DRAFT", canonical_account_name="Draft Account", normalized_account_name="draft account",
        )
        AccountMineSiteMapping.objects.create(
            business_account=draft_account, minesite=self.site, account_role="Parts Account",
            relationship_status="Draft", valid_from=date(2026, 1, 1),
        )
        response = self.client.get(reverse("business-review-overview-api"), {"lens": "PARTS"}).json()
        self.assertTrue(response["ready"])
        self.assertEqual(response["context"]["published_mapping_version"], publication.version)
        self.assertEqual(response["metrics"]["published_account_count"], 1)
        self.assertEqual(response["metrics"]["mining_revenue_ytd_eur"], 1000)
        self.assertEqual(BusinessReviewSnapshot.objects.count(), 1)

    def test_manager_can_view_review_but_cannot_open_mapping_studio(self):
        self.publish()
        manager = User.objects.create_user("manager", "manager@example.com", "password")
        manager.user_permissions.add(Permission.objects.get(codename="view_business_review"))
        self.client.force_login(manager)
        self.assertEqual(self.client.get(reverse("business-review")).status_code, 200)
        self.assertEqual(self.client.get(reverse("business-mapping-studio")).status_code, 403)

    def test_portfolio_classification_requires_validated_threshold(self):
        self.publish()
        no_rule = self.client.get(reverse("business-review-portfolio-api"), {"lens": "PARTS"}).json()
        self.assertEqual(no_rule["thresholds"]["status"], "NOT_CONFIGURED")
        self.assertIsNone(no_rule["results"][0]["classification"])
        BusinessPortfolioThresholdRule.objects.create(
            code="PARTS-GROUP-2026", revenue_lens="PARTS", method="Fixed Governed Threshold",
            revenue_threshold=2000, fleet_threshold=1, effective_from=date(2026, 1, 1),
            rule_version="1.0", validation_status="Validated", owner=self.admin,
        )
        governed = self.client.get(reverse("business-review-portfolio-api"), {"lens": "PARTS"}).json()
        self.assertEqual(governed["thresholds"]["status"], "READY")
        self.assertEqual(governed["results"][0]["classification"], "Commercial Opportunity")

    def test_management_action_is_persisted_against_published_snapshot(self):
        self.publish()
        response = self.client.post(
            reverse("business-review-actions-api"),
            data=json.dumps({"title": "Review Parts capture", "priority": "High", "minesite_id": str(self.site.id)}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        action = BusinessReviewAction.objects.get()
        self.assertEqual(action.title, "Review Parts capture")
        self.assertEqual(action.snapshot.mapping_publication.version, 1)
        self.assertEqual(self.client.get(reverse("business-review-actions-api")).json()["results"][0]["status"], "Open")
        self.assertTrue(MappingAuditLog.objects.filter(action="BUSINESS_REVIEW_ACTION_CREATED", entity_id=str(action.id)).exists())

    def test_global_filters_are_enforced_by_the_backend(self):
        self.publish()
        available = self.client.get(reverse("business-review-overview-api"), {"country": "ML"}).json()
        self.assertEqual(available["metrics"]["published_account_count"], 1)
        self.assertEqual(available["filter_options"]["countries"], ["ML"])
        excluded = self.client.get(reverse("business-review-overview-api"), {"country": "CI"}).json()
        self.assertEqual(excluded["metrics"]["published_account_count"], 0)
        self.assertIsNone(excluded["metrics"]["unallocated_revenue_eur"])
        self.assertEqual(excluded["confidence"]["status"], "Not Ready")
        self.assertIsNone(excluded["confidence"]["revenue_coverage"])

    def test_later_publication_remains_a_complete_snapshot(self):
        first = self.publish()
        second_account = BusinessAccount.objects.create(
            canonical_account_code="ACC-BONIKRO", canonical_account_name="Bonikro Account", normalized_account_name="bonikro account",
        )
        SourceAccountRecord.objects.create(
            source_system="MiningAccounts", source_record_id="C002", source_account_name="Bonikro Account",
            normalized_account_name="bonikro account", canonical_account=second_account, source_hash="source-2",
            source_last_seen_at="2026-09-05T13:00:00Z", synchronization_run=self.run,
        )
        AccountMineSiteMapping.objects.create(
            business_account=second_account, minesite=self.site, account_role="Parts Account",
            relationship_status="Validated", valid_from=date(2026, 1, 1),
        )
        second = MappingPublicationService(self.admin).publish("Second complete version")
        self.assertEqual(first.mapping_count, 1)
        self.assertEqual(second.mapping_count, 2)
        self.assertEqual({row["account_code"] for row in second.snapshot_json["mappings"]}, {"ACC-FEKOLA", "ACC-BONIKRO"})

    @override_settings(ENABLE_BUSINESS_REVIEW_EXPORT="Production")
    def test_export_contains_published_review_contract(self):
        self.publish()
        response = self.client.get(reverse("business-review-export-api"), {"lens": "PARTS"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertIn("Business_Review_v1_PARTS", response["Content-Disposition"])
        self.assertGreater(len(response.content), 5000)
