from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from .models import (
    MappingSynchronizationRun,
    PartSaleDetail,
    PartsSalesSynchronizationRun,
    ReconciliationRun,
    ReconciliationSourceSnapshot,
    RevenueSourceSnapshot,
)
from .parts_sales_service import PartsSalesDetailService


class PartsSalesDetailServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="parts-admin", email="parts@example.com", password="test-password"
        )
        snapshots = {}
        for kind in ("ORDERS", "DELIVERY_INVOICE", "INVOICES", "ACCOUNTING_REVENUE"):
            snapshots[kind] = ReconciliationSourceSnapshot.objects.create(
                source_kind=kind,
                source_name=f"test-{kind}",
                source_version="v1",
                status="Ready",
                extracted_at=timezone.now(),
            )
        reconciliation = ReconciliationRun.objects.create(
            order_snapshot=snapshots["ORDERS"],
            link_snapshot=snapshots["DELIVERY_INVOICE"],
            invoice_snapshot=snapshots["INVOICES"],
            accounting_snapshot=snapshots["ACCOUNTING_REVENUE"],
            rule_version="parts-test-v1",
            status="Completed",
        )
        parts_run = PartsSalesSynchronizationRun.objects.create(
            reconciliation_run=reconciliation,
            status="Completed with Warnings",
            data_through_date=date(2026, 6, 30),
            completed_at=timezone.now(),
        )
        now = timezone.now()
        PartSaleDetail.objects.create(
            source_record_id="line-1", business_date=date(2026, 3, 1), customer_code="C1",
            invoice_number="F1", part_number="1R-1808", normalized_part_number="1R1808",
            brand="CAT", brand_group="CAT",
            major_class_code="7", major_class_description="FILTERS AND FLUIDS",
            minor_class="10", ppc="FILTER", classification_status="Classified",
            allocated_revenue_eur=Decimal("80"), source_hash="a" * 64,
            synchronization_run=parts_run, source_last_seen_at=now,
        )
        PartSaleDetail.objects.create(
            source_record_id="line-2", business_date=date(2026, 3, 2), customer_code="C1",
            invoice_number="F2", part_number="UNKNOWN", normalized_part_number="UNKNOWN",
            brand="EPIROC", brand_group="Other Brands",
            classification_status="Other Brand", allocated_revenue_eur=Decimal("20"),
            source_hash="b" * 64, synchronization_run=parts_run, source_last_seen_at=now,
        )
        mapping_run = MappingSynchronizationRun.objects.create(status="Completed")
        RevenueSourceSnapshot.objects.create(
            synchronization_run=mapping_run, source_record_id="revenue-1", source_account_code="C1",
            business_date=date(2026, 3, 1), lob="PARTS", division="MI",
            revenue_eur=Decimal("125"), source_hash="c" * 64, source_last_seen_at=now,
        )

    def test_major_grouping_and_coverage_are_distinct(self):
        result = PartsSalesDetailService(self.user, {
            "start_date": "2026-01-01", "end_date": "2026-12-31", "group_by": "major",
        }).result()

        self.assertTrue(result["ready"])
        self.assertEqual(result["results"][0]["major_class"], "7")
        self.assertEqual(result["results"][0]["brand_group"], "CAT")
        self.assertEqual(result["results"][1]["brand_group"], "Other Brands")
        self.assertEqual(result["summary"]["certified_parts_revenue_eur"], 125.0)
        self.assertEqual(result["summary"]["allocated_invoice_revenue_eur"], 100.0)
        self.assertEqual(result["summary"]["classified_revenue_eur"], 80.0)
        self.assertEqual(result["summary"]["reconciliation_coverage_pct"], 80.0)
        self.assertEqual(result["summary"]["classification_coverage_pct"], 80.0)

    def test_minor_and_ppc_filters_preserve_major_code(self):
        result = PartsSalesDetailService(self.user, {
            "start_date": "2026-01-01", "end_date": "2026-12-31",
            "group_by": "ppc", "major": "7", "minor": "10", "ppc": "FILTER",
        }).result()

        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["major_class"], "7")
        self.assertEqual(result["results"][0]["minor_class"], "10")
        self.assertEqual(result["results"][0]["ppc"], "FILTER")
