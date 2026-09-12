from collections import defaultdict
from decimal import Decimal
import re

from django.db import connection, transaction
from django.db.models import Case, CharField, Count, F, Q, Subquery, Value, When
from django.utils import timezone

from .models import (
    ReconciliationAccountingEntry,
    ReconciliationDeliveryInvoiceLink,
    ReconciliationInvoiceHeader,
    ReconciliationMatch,
    ReconciliationMatchAccountingEntry,
    ReconciliationOrderLine,
    ReconciliationRun,
    ReconciliationSourceSnapshot,
)


class ReconciliationConfigurationError(ValueError):
    pass


def _token(value):
    token = " ".join(str(value or "").strip().upper().split())
    if re.fullmatch(r"-?\d+(?:\.0+)?", token):
        return str(int(token.split(".", 1)[0]))
    return token


def _order_key(record):
    return (
        _token(record.company_code),
        _token(getattr(record, "branch_code", None) or getattr(record, "order_branch_code", None)),
        _token(record.order_number),
        _token(record.line_number),
    )


def _invoice_key(record):
    return (
        _token(record.company_code),
        _token(getattr(record, "branch_code", None) or getattr(record, "invoice_branch_code", None)),
        _token(record.invoice_number),
    )


def _display_key(parts):
    return "|".join(parts)


class RevenueOrderReconciliationService:
    """Deterministic NEG_LIG -> NEG_LLF -> NEG_FAC -> accounting reconciliation."""

    def __init__(self, user=None, rule_version="draft-neg-llf-v3-numeric-identifiers"):
        self.user = user
        self.rule_version = rule_version

    @staticmethod
    def _materialize_order_billing_statuses(run):
        orders = ReconciliationOrderLine.objects.filter(snapshot=run.order_snapshot)
        orders.update(
            ca_combine_present=False,
            billing_status=Case(
                When(
                    Q(current_delivered_quantity__gt=0)
                    & (Q(current_invoiced_quantity__isnull=True) | Q(current_invoiced_quantity__lte=0)),
                    then=Value("NOT_INVOICED"),
                ),
                When(current_delivered_quantity__gt=0, then=Value("TO_INVESTIGATE")),
                default=Value("NOT_DELIVERED"), output_field=CharField(),
            ),
        )
        accounting_order_ids = ReconciliationMatchAccountingEntry.objects.filter(
            match__run=run, match__order_line_id__isnull=False,
        ).values("match__order_line_id")
        orders.filter(pk__in=Subquery(accounting_order_ids)).update(
            ca_combine_present=True,
            billing_status=Case(
                When(
                    ordered_quantity__isnull=False,
                    current_invoiced_quantity__lt=F("ordered_quantity"),
                    then=Value("PARTIALLY_INVOICED"),
                ),
                default=Value("INVOICED"), output_field=CharField(),
            ),
        )

    @staticmethod
    def _require_snapshot(snapshot, expected_kind):
        if snapshot.source_kind != expected_kind:
            raise ReconciliationConfigurationError(
                f"Expected {expected_kind} snapshot, received {snapshot.source_kind}."
            )
        if snapshot.status not in {"Ready", "Ready with Warnings"}:
            raise ReconciliationConfigurationError(
                f"Snapshot {snapshot.pk} is not ready."
            )

    def execute(self, *, order_snapshot, link_snapshot, invoice_snapshot, accounting_snapshot):
        self._require_snapshot(order_snapshot, "ORDERS")
        self._require_snapshot(link_snapshot, "DELIVERY_INVOICE")
        self._require_snapshot(invoice_snapshot, "INVOICES")
        self._require_snapshot(accounting_snapshot, "ACCOUNTING_REVENUE")

        existing = ReconciliationRun.objects.filter(
            order_snapshot=order_snapshot,
            link_snapshot=link_snapshot,
            invoice_snapshot=invoice_snapshot,
            accounting_snapshot=accounting_snapshot,
            rule_version=self.rule_version,
        ).first()
        if existing and existing.status in {"Completed", "Completed with Warnings"}:
            self._materialize_order_billing_statuses(existing)
            return existing

        if existing:
            run = existing
            run.status = "Running"
            run.completed_at = None
            run.save(update_fields=["status", "completed_at"])
        else:
            run = ReconciliationRun.objects.create(
                order_snapshot=order_snapshot,
                link_snapshot=link_snapshot,
                invoice_snapshot=invoice_snapshot,
                accounting_snapshot=accounting_snapshot,
                rule_version=self.rule_version,
                status="Running",
                started_at=timezone.now(),
                initiated_by=self.user,
            )

        orders = defaultdict(list)
        order_rows = ReconciliationOrderLine.objects.filter(snapshot=order_snapshot).values_list(
            "id", "company_code", "branch_code", "order_number", "line_number", "ordered_quantity"
        )
        for row_id, company, branch, number, line, quantity in order_rows.iterator(chunk_size=10000):
            orders[tuple(map(_token, (company, branch, number, line)))].append((row_id, quantity))

        invoices = defaultdict(list)
        invoice_rows = ReconciliationInvoiceHeader.objects.filter(snapshot=invoice_snapshot).values_list(
            "id", "company_code", "branch_code", "invoice_number"
        )
        for row_id, company, branch, number in invoice_rows.iterator(chunk_size=10000):
            invoices[tuple(map(_token, (company, branch, number)))].append(row_id)

        accounting = defaultdict(list)
        accounting_rows = ReconciliationAccountingEntry.objects.filter(snapshot=accounting_snapshot).values_list(
            "id", "company_code", "document_number", "entry_type"
        )
        for row_id, company, document, entry_type in accounting_rows.iterator(chunk_size=10000):
            accounting[(_token(company), _token(document))].append((row_id, entry_type))

        link_fields = (
            "id", "company_code", "order_branch_code", "order_number", "line_number",
            "invoice_number", "invoice_branch_code", "cancellation_invoice_number", "invoiced_quantity",
        )
        all_links = ReconciliationDeliveryInvoiceLink.objects.filter(snapshot=link_snapshot).values_list(*link_fields)
        invoiced_by_order = defaultdict(Decimal)
        for link in all_links.iterator(chunk_size=10000):
            _, company, order_branch, order_number, line_number, _, _, cancellation, quantity = link
            if not cancellation and quantity is not None:
                order_key = tuple(map(_token, (company, order_branch, order_number, line_number)))
                invoiced_by_order[order_key] += quantity

        processed_link_ids = ReconciliationMatch.objects.filter(run=run).values_list(
            "delivery_invoice_link_id", flat=True
        )
        pending_links = ReconciliationDeliveryInvoiceLink.objects.filter(snapshot=link_snapshot).exclude(
            id__in=processed_link_ids
        ).values_list(*link_fields)
        match_batch = []
        accounting_ids_by_match = []
        batch_size = 2000

        def flush_batch():
            if not match_batch:
                return
            with transaction.atomic():
                ReconciliationMatch.objects.bulk_create(match_batch, batch_size=batch_size)
                if not connection.features.can_return_rows_from_bulk_insert or any(item.pk is None for item in match_batch):
                    raise ReconciliationConfigurationError(
                        "The database cannot return identifiers for batched reconciliation rows."
                    )
                through_rows = []
                for match, accounting_ids in zip(match_batch, accounting_ids_by_match):
                    through_rows.extend(
                        ReconciliationMatchAccountingEntry(match_id=match.pk, accounting_entry_id=entry_id)
                        for entry_id in accounting_ids
                    )
                ReconciliationMatchAccountingEntry.objects.bulk_create(through_rows, batch_size=batch_size)
            match_batch.clear()
            accounting_ids_by_match.clear()

        for link in pending_links.iterator(chunk_size=10000):
            link_id, company, order_branch, order_number, line_number, invoice_number, invoice_branch, cancellation, _ = link
            order_key = tuple(map(_token, (company, order_branch, order_number, line_number)))
            invoice_key = tuple(map(_token, (company, invoice_branch, invoice_number)))
            order_candidates = orders.get(order_key, [])
            invoice_candidates = invoices.get(invoice_key, []) if invoice_number else []
            accounting_candidates = accounting.get(
                (_token(company), _token(invoice_number)), []
            ) if invoice_number else []
            warnings = []
            matched_by = ["NEG_LLF_SOURCE_ROW"]

            if not order_candidates:
                status = "MISSING_ORDER"
            elif len(order_candidates) > 1:
                status = "AMBIGUOUS_ORDER"
            elif cancellation:
                status = "CANCELLED"
                matched_by.append("NLLF_NUMFACANN")
            elif not invoice_candidates:
                status = "MISSING_INVOICE"
            elif len(invoice_candidates) > 1:
                status = "AMBIGUOUS_INVOICE"
            elif not accounting_candidates:
                status = "MISSING_ACCOUNTING"
            else:
                _, ordered_quantity = order_candidates[0]
                total_invoiced = invoiced_by_order[order_key]
                if ordered_quantity is not None and total_invoiced < ordered_quantity:
                    status = "PARTIALLY_INVOICED"
                else:
                    status = "MATCHED"
                matched_by.extend([
                    "EXACT_ORDER_COMPANY_BRANCH_NUMBER_LINE",
                    "EXACT_INVOICE_COMPANY_ISSUER_BRANCH_NUMBER",
                    "EXACT_ACCOUNTING_DOCUMENT_COMPANY",
                ])

            if len(accounting_candidates) > 1:
                warnings.append("MULTIPLE_ACCOUNTING_ENTRIES_FOR_INVOICE")
            if any(_token(entry_type) in {"FAE", "ACCRUAL"} for _, entry_type in accounting_candidates):
                warnings.append("ACCOUNTING_ENTRY_TYPE_REQUIRES_REVIEW")

            match_batch.append(ReconciliationMatch(
                run=run,
                delivery_invoice_link_id=link_id,
                order_line_id=order_candidates[0][0] if len(order_candidates) == 1 else None,
                invoice_header_id=invoice_candidates[0] if len(invoice_candidates) == 1 else None,
                status=status,
                confidence_score=Decimal("100.00") if status in {"MATCHED", "PARTIALLY_INVOICED"} else Decimal("0.00"),
                matched_by_json=matched_by,
                warnings_json=warnings,
                order_key=_display_key(order_key),
                invoice_key=_display_key(invoice_key) if invoice_number else "",
            ))
            accounting_ids_by_match.append([entry_id for entry_id, _ in accounting_candidates])
            if len(match_batch) >= batch_size:
                flush_batch()
        flush_batch()
        self._materialize_order_billing_statuses(run)

        status_counts = {
            row["status"]: row["count"]
            for row in run.matches.values("status").annotate(count=Count("id"))
        }
        warning_count = sum(len(value) for value in run.matches.values_list("warnings_json", flat=True).iterator())
        matched_invoice_count = run.matches.exclude(invoice_header=None).values("invoice_header_id").distinct().count()
        matched_accounting_count = ReconciliationMatchAccountingEntry.objects.filter(
            match__run=run
        ).values("accounting_entry_id").distinct().count()
        run.summary_json = {
            "link_rows_processed": run.matches.count(),
            "status_counts": dict(sorted(status_counts.items())),
            "distinct_invoice_headers_matched": matched_invoice_count,
            "distinct_accounting_entries_matched": matched_accounting_count,
            "warning_count": warning_count,
            "certification_status": "NOT_CERTIFIED",
        }
        run.warnings_json = [
            "Source cardinality and business rules require validation on real invoice examples."
        ] if warning_count or any(key not in {"MATCHED"} for key in status_counts) else []
        run.status = "Completed with Warnings" if run.warnings_json else "Completed"
        run.completed_at = timezone.now()
        run.save(update_fields=["summary_json", "warnings_json", "status", "completed_at"])
        return run
