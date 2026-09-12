from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    PlatformUser,
    ReconciliationAccountingEntry,
    ReconciliationDeliveryInvoiceLink,
    ReconciliationInvoiceHeader,
    ReconciliationOrderHeader,
    ReconciliationOrderLine,
    ReconciliationSourceSnapshot,
    ReconciliationBufferSyncRun,
)
from .reconciliation_service import RevenueOrderReconciliationService
from .reconciliation_buffer_service import SemanticReconciliationBufferService


class RevenueOrderReconciliationServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("reconciliation-user")
        self.orders = self.snapshot("ORDERS", "NEG_LIG")
        self.links = self.snapshot("DELIVERY_INVOICE", "NEG_LLF")
        self.invoices = self.snapshot("INVOICES", "NEG_FAC")
        self.accounting = self.snapshot("ACCOUNTING_REVENUE", "CA Combine")
        self.service = RevenueOrderReconciliationService(self.user)

    @staticmethod
    def snapshot(kind, name):
        return ReconciliationSourceSnapshot.objects.create(
            source_kind=kind,
            source_name=name,
            source_version="fixture-v1",
            status="Ready",
            extracted_at=timezone.now(),
        )

    def order(self, quantity=10):
        return ReconciliationOrderLine.objects.create(
            snapshot=self.orders,
            source_record_id="ORDER-ROW-1",
            company_code="27",
            branch_code="01",
            order_number="CMD-100",
            line_number="1",
            customer_number="CUSTOMER-1",
            part_number="PART-1",
            ordered_quantity=quantity,
            order_date=date(2026, 8, 1),
        )

    def link(self, source_id, invoice, quantity, cancellation=""):
        return ReconciliationDeliveryInvoiceLink.objects.create(
            snapshot=self.links,
            source_record_id=source_id,
            company_code="27",
            order_branch_code="01",
            order_number="CMD-100",
            line_number="1",
            customer_number="CUSTOMER-1",
            invoice_number=invoice,
            cancellation_invoice_number=cancellation,
            invoice_branch_code="02",
            invoice_service_code="PARTS",
            part_number="PART-1",
            invoiced_quantity=quantity,
        )

    def invoice(self, number):
        return ReconciliationInvoiceHeader.objects.create(
            snapshot=self.invoices,
            source_record_id=f"INVOICE-{number}",
            company_code="27",
            branch_code="02",
            service_code="PARTS",
            invoice_number=number,
            customer_number="CUSTOMER-1",
            invoice_date=date(2026, 8, 15),
            transaction_origin="D",
        )

    def accounting_entry(self, source_id, invoice, amount, entry_type="INVOICE"):
        return ReconciliationAccountingEntry.objects.create(
            snapshot=self.accounting,
            source_record_id=source_id,
            company_code="27",
            document_number=invoice,
            entry_type=entry_type,
            accounting_date=date(2026, 8, 16),
            consolidated_amount=Decimal(str(amount)),
        )

    def execute(self):
        return self.service.execute(
            order_snapshot=self.orders,
            link_snapshot=self.links,
            invoice_snapshot=self.invoices,
            accounting_snapshot=self.accounting,
        )

    def test_partial_invoicing_uses_all_neg_llf_rows_for_the_order_line(self):
        self.order(quantity=10)
        self.link("LLF-1", "FAC-1", 4)
        self.link("LLF-2", "FAC-2", 3)
        self.invoice("FAC-1")
        self.invoice("FAC-2")
        self.accounting_entry("CA-1", "FAC-1", 400)
        self.accounting_entry("CA-2", "FAC-2", 300)

        run = self.execute()

        self.assertEqual(run.summary_json["status_counts"], {"PARTIALLY_INVOICED": 2})
        self.assertEqual(run.summary_json["distinct_invoice_headers_matched"], 2)
        self.assertEqual(run.matches.values("order_line_id").distinct().count(), 1)

    def test_complete_multi_invoice_order_is_matched(self):
        self.order(quantity=10)
        self.link("LLF-1", "FAC-1", 4)
        self.link("LLF-2", "FAC-2", 6)
        self.invoice("FAC-1")
        self.invoice("FAC-2")
        self.accounting_entry("CA-1", "FAC-1", 400)
        self.accounting_entry("CA-2", "FAC-2", 600)

        run = self.execute()

        self.assertEqual(run.summary_json["status_counts"], {"MATCHED": 2})

    def test_numeric_semantic_keys_match_integer_and_decimal_text(self):
        order = self.order(quantity=10)
        order.order_number = "22110708.0"
        order.line_number = "168"
        order.save(update_fields=["order_number", "line_number"])
        link = self.link("LLF-1", "22017619.0", 10)
        link.order_number = "22110708.0"
        link.line_number = "168.0"
        link.save(update_fields=["order_number", "line_number"])
        invoice = self.invoice("22017619.0")
        invoice.company_code = "27.0"
        invoice.branch_code = "2.0"
        invoice.save(update_fields=["company_code", "branch_code"])
        entry = self.accounting_entry("CA-1", "22017619.0", 600)
        entry.company_code = "027"
        entry.save(update_fields=["company_code"])

        run = self.execute()

        self.assertEqual(run.summary_json["status_counts"], {"MATCHED": 1})

    def test_multiple_accounting_lines_do_not_duplicate_invoice_count(self):
        self.order(quantity=10)
        self.link("LLF-1", "FAC-1", 10)
        self.invoice("FAC-1")
        self.accounting_entry("CA-1", "FAC-1", 600)
        self.accounting_entry("CA-2", "FAC-1", 400)

        run = self.execute()
        match = run.matches.get()

        self.assertEqual(run.summary_json["distinct_invoice_headers_matched"], 1)
        self.assertEqual(run.summary_json["distinct_accounting_entries_matched"], 2)
        self.assertEqual(match.accounting_entries.count(), 2)
        self.assertIn("MULTIPLE_ACCOUNTING_ENTRIES_FOR_INVOICE", match.warnings_json)

    def test_logical_cancellation_is_not_marked_as_matched(self):
        self.order(quantity=10)
        self.link("LLF-1", "FAC-1", 10, cancellation="FAC-ANN-1")
        self.invoice("FAC-1")
        self.accounting_entry("CA-1", "FAC-1", 1000)

        run = self.execute()

        self.assertEqual(run.matches.get().status, "CANCELLED")
        self.assertIn("NLLF_NUMFACANN", run.matches.get().matched_by_json)

    def test_missing_invoice_is_a_controlled_exception(self):
        self.order(quantity=10)
        self.link("LLF-1", "FAC-UNKNOWN", 10)

        run = self.execute()

        self.assertEqual(run.matches.get().status, "MISSING_INVOICE")
        self.assertEqual(run.status, "Completed with Warnings")

    def test_same_snapshot_contract_is_idempotent(self):
        self.order(quantity=10)
        self.link("LLF-1", "FAC-1", 10)
        self.invoice("FAC-1")
        self.accounting_entry("CA-1", "FAC-1", 1000)

        first = self.execute()
        second = self.execute()

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(first.matches.count(), 1)


class InvoiceTrackingInterfaceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("invoice-admin", "invoice@example.com", "password")
        self.client = Client()
        self.client.force_login(self.user)

    def test_page_and_empty_apis_render_without_fake_results(self):
        page = self.client.get(reverse("invoice-tracking"))
        overview = self.client.get(reverse("invoice-tracking-overview-api"))
        rows = self.client.get(reverse("invoice-tracking-rows-api"))

        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Invoice Tracking Detailed")
        self.assertEqual(overview.status_code, 200)
        self.assertIsNone(overview.json()["reconciliation"])
        self.assertEqual(rows.json()["count"], 0)
        self.assertEqual(rows.json()["results"], [])

    def test_platform_administrator_sees_invoice_tracking_under_config(self):
        self.user.is_superuser = False
        self.user.is_staff = False
        self.user.save(update_fields=["is_superuser", "is_staff"])
        PlatformUser.objects.create(
            django_user=self.user,
            azure_ad_id="invoice-platform-admin",
            user_principal_name="invoice-platform-admin@example.com",
            display_name="Invoice Platform Admin",
            is_platform_admin=True,
        )

        page = self.client.get(reverse("invoice-tracking"))

        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'data-nav-group="config"')
        self.assertContains(page, f'href="{reverse("invoice-tracking")}"')
        self.assertContains(page, "Invoice Tracking")

    def test_ajax_synchronization_creates_one_reusable_run(self):
        from unittest.mock import patch

        endpoint = reverse("invoice-tracking-sync-api")
        with patch("reports.reconciliation_views.SemanticReconciliationBufferService.start_background"):
            first = self.client.post(endpoint)
            second = self.client.post(endpoint)

        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 200)
        self.assertFalse(first.json()["reused"])
        self.assertTrue(second.json()["reused"])
        self.assertEqual(ReconciliationBufferSyncRun.objects.count(), 1)

    def test_sync_status_returns_real_persisted_progress(self):
        run = ReconciliationBufferSyncRun.objects.create(
            status="Running", progress_percent=40, stage_code="invoices",
            stage_label="Retrieving Invoices", initiated_by=self.user,
        )
        response = self.client.get(reverse("invoice-tracking-sync-status-api", args=[run.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["sync"]["progress_percent"], 40)
        self.assertEqual(response.json()["sync"]["stage_label"], "Retrieving Invoices")

    def test_order_billing_view_includes_delivered_line_without_ca_combine(self):
        orders = ReconciliationSourceSnapshot.objects.create(
            source_kind="ORDERS", source_name="Mine Logistics Report",
            source_version="sync-1:ORDERS", status="Ready", extracted_at=timezone.now(),
        )
        links = ReconciliationSourceSnapshot.objects.create(
            source_kind="DELIVERY_INVOICE", source_name="Mine Logistics Report",
            source_version="sync-1:DELIVERY_INVOICE", status="Ready", extracted_at=timezone.now(),
        )
        invoices = ReconciliationSourceSnapshot.objects.create(
            source_kind="INVOICES", source_name="Mine Logistics Report",
            source_version="sync-1:INVOICES", status="Ready", extracted_at=timezone.now(),
        )
        accounting = ReconciliationSourceSnapshot.objects.create(
            source_kind="ACCOUNTING_REVENUE", source_name="CA Combine",
            source_version="sync-1:ACCOUNTING_REVENUE", status="Ready", extracted_at=timezone.now(),
        )
        headers = ReconciliationSourceSnapshot.objects.create(
            source_kind="ORDER_HEADERS", source_name="Mine Logistics Report",
            source_version="sync-1:ORDER_HEADERS", status="Ready", extracted_at=timezone.now(),
        )
        header = ReconciliationOrderHeader.objects.create(
            snapshot=headers, source_record_id="HEADER-1", company_code="36", branch_code="91",
            order_number="41148402", customer_number="C-1",
            order_type="Parts", transport="Air", eta=date(2026, 9, 15),
        )
        ReconciliationOrderLine.objects.create(
            snapshot=orders, order_header=header, source_record_id="LINE-1", company_code="36", branch_code="91",
            order_number="41148402", line_number="190", customer_number="C-1", customer_name="Mining Customer",
            part_number="2139100",
            order_date=date(2026, 9, 1), ordered_quantity=1, current_delivered_quantity=1,
            current_invoiced_quantity=0, status="Delivered",
        )
        RevenueOrderReconciliationService(self.user).execute(
            order_snapshot=orders, link_snapshot=links, invoice_snapshot=invoices,
            accounting_snapshot=accounting,
        )

        response = self.client.get(reverse("invoice-tracking-rows-api"), {"view": "orders"})

        self.assertEqual(response.status_code, 200)
        row = response.json()["results"][0]
        self.assertEqual(row["billing_status"], "NOT_INVOICED")
        self.assertFalse(row["ca_combine_present"])
        self.assertEqual(row["customer"], "Mining Customer")
        self.assertEqual(row["customer_name"], "Mining Customer")
        self.assertEqual(row["order_type"], "Parts")
        self.assertEqual(row["transport"], "Air")

        in_period = self.client.get(reverse("invoice-tracking-rows-api"), {
            "view": "orders", "date_from": "2026-09-01", "date_to": "2026-09-30",
        })
        outside_period = self.client.get(reverse("invoice-tracking-rows-api"), {
            "view": "orders", "date_from": "2026-10-01", "date_to": "2026-10-31",
        })
        self.assertEqual(in_period.json()["count"], 1)
        self.assertEqual(outside_period.json()["count"], 0)

        header_match = self.client.get(reverse("invoice-tracking-rows-api"), {
            "view": "orders", "header_customer": "Mining", "header_order_type": "Parts",
            "header_transport": "Air",
        })
        header_miss = self.client.get(reverse("invoice-tracking-rows-api"), {
            "view": "orders", "header_order_type": "Service",
        })
        self.assertEqual(header_match.json()["count"], 1)
        self.assertEqual(header_miss.json()["count"], 0)
        self.assertIn("Parts", header_match.json()["filters"]["order_headers"]["order_type"])

    def test_order_header_link_uses_the_semantic_model_relationship_key(self):
        orders = ReconciliationSourceSnapshot.objects.create(
            source_kind="ORDERS", source_name="Mine Logistics Report",
            source_version="sync-key:ORDERS", status="Ready", extracted_at=timezone.now(),
        )
        headers = ReconciliationSourceSnapshot.objects.create(
            source_kind="ORDER_HEADERS", source_name="Mine Logistics Report",
            source_version="sync-key:ORDER_HEADERS", status="Ready", extracted_at=timezone.now(),
        )
        header = ReconciliationOrderHeader.objects.create(
            snapshot=headers, source_record_id="HEADER-KEY", semantic_order_key="SEMANTIC-1",
            company_code="27", branch_code="01", order_number="HEADER-ORDER",
            customer_number="C-9", customer_name="Semantic Customer",
        )
        order = ReconciliationOrderLine.objects.create(
            snapshot=orders, source_record_id="LINE-KEY", semantic_order_key="SEMANTIC-1",
            company_code="99", branch_code="99", order_number="DIFFERENT-ORDER", line_number="1",
        )

        linked = SemanticReconciliationBufferService._link_order_headers(orders, headers)

        order.refresh_from_db()
        self.assertEqual(linked, 1)
        self.assertEqual(order.order_header_id, header.pk)

    def test_order_billing_view_flags_source_invoiced_without_ca_for_investigation(self):
        orders = ReconciliationSourceSnapshot.objects.create(
            source_kind="ORDERS", source_name="Mine Logistics Report",
            source_version="sync-2:ORDERS", status="Ready", extracted_at=timezone.now(),
        )
        links = ReconciliationSourceSnapshot.objects.create(
            source_kind="DELIVERY_INVOICE", source_name="Mine Logistics Report",
            source_version="sync-2:DELIVERY_INVOICE", status="Ready", extracted_at=timezone.now(),
        )
        invoices = ReconciliationSourceSnapshot.objects.create(
            source_kind="INVOICES", source_name="Mine Logistics Report",
            source_version="sync-2:INVOICES", status="Ready", extracted_at=timezone.now(),
        )
        accounting = ReconciliationSourceSnapshot.objects.create(
            source_kind="ACCOUNTING_REVENUE", source_name="CA Combine",
            source_version="sync-2:ACCOUNTING_REVENUE", status="Ready", extracted_at=timezone.now(),
        )
        ReconciliationOrderLine.objects.create(
            snapshot=orders, source_record_id="LINE-2", company_code="36", branch_code="91",
            order_number="41145580", line_number="65", ordered_quantity=1,
            current_delivered_quantity=1, current_invoiced_quantity=1, status="Delivered",
        )
        RevenueOrderReconciliationService(self.user).execute(
            order_snapshot=orders, link_snapshot=links, invoice_snapshot=invoices,
            accounting_snapshot=accounting,
        )

        response = self.client.get(reverse("invoice-tracking-rows-api"), {"view": "orders"})

        self.assertEqual(response.json()["results"][0]["billing_status"], "TO_INVESTIGATE")
