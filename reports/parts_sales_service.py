from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone

from .business_mapping_access_service import authorized_account_codes
from .models import (
    PartClassificationReference,
    PartSaleDetail,
    PartsSalesSynchronizationRun,
    ReconciliationAccountingEntry,
    ReconciliationDeliveryInvoiceLink,
    ReconciliationOrderLine,
    ReconciliationRun,
    RevenueSourceSnapshot,
)
from .reconciliation_service import _token


def _text(value):
    return str(value or "").strip()


def _part_key(value):
    return "".join(character for character in _text(value).upper() if character.isalnum())


def _hash(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


class PartsSalesSynchronizationService:
    BATCH_SIZE = 2000
    UPDATE_BATCH_SIZE = 100

    @classmethod
    def synchronize(cls):
        reconciliation = ReconciliationRun.objects.filter(
            status__in=["Completed", "Completed with Warnings"]
        ).first()
        if not reconciliation:
            raise RuntimeError("A completed Invoice Tracking reconciliation is required.")
        run = PartsSalesSynchronizationRun.objects.create(reconciliation_run=reconciliation)
        now = timezone.now()
        counters = defaultdict(int)
        allocated_total = Decimal("0")
        try:
            accounting = {}
            rows = ReconciliationAccountingEntry.objects.filter(
                snapshot=reconciliation.accounting_snapshot
            ).values_list(
                "company_code", "document_number", "accounting_date", "customer_number",
                "consolidated_amount", "source_payload_json",
            )
            for company, document, business_date, customer, amount, source_payload in rows.iterator(chunk_size=10000):
                key = (_token(company), _token(document))
                item = accounting.setdefault(key, {
                    "amount": Decimal("0"), "date": business_date,
                    "customer": _text(customer), "name": "",
                })
                item["amount"] += amount or Decimal("0")
                if business_date and (not item["date"] or business_date > item["date"]):
                    item["date"] = business_date
                item["customer"] = item["customer"] or _text(customer)
                item["name"] = item["name"] or _text((source_payload or {}).get("[entry_label]"))

            order_brands = {
                (_token(company), _token(branch), _token(order), _token(line)): _text(brand)
                for company, branch, order, line, brand in ReconciliationOrderLine.objects.filter(
                    snapshot=reconciliation.order_snapshot
                ).values_list("company_code", "branch_code", "order_number", "line_number", "brand").iterator(
                    chunk_size=10000
                )
            }

            pending = []
            current_key = None
            invoice_lines = []
            invoice_brands = {}
            links = ReconciliationDeliveryInvoiceLink.objects.filter(
                snapshot=reconciliation.link_snapshot,
                cancellation_invoice_number="",
            ).exclude(invoice_number="").order_by("company_code", "invoice_number", "id")

            def consume_invoice(key, source_lines):
                nonlocal allocated_total, pending
                certified = accounting.get(key)
                if not certified or not certified["date"]:
                    return
                line_total = sum((line.net_amount or Decimal("0") for line in source_lines), Decimal("0"))
                if line_total == 0:
                    counters["zero_value_invoice"] += 1
                    return
                remaining = certified["amount"]
                for index, line in enumerate(source_lines):
                    if index == len(source_lines) - 1:
                        allocated = remaining
                    else:
                        allocated = (
                            certified["amount"] * (line.net_amount or Decimal("0")) / line_total
                        ).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
                        remaining -= allocated
                    pending.append({
                        "source_record_id": line.source_record_id,
                        "business_date": certified["date"],
                        "company_code": line.company_code,
                        "branch_code": line.invoice_branch_code,
                        "customer_code": certified["customer"] or line.customer_number,
                        "customer_name": certified["name"],
                        "invoice_number": _token(line.invoice_number),
                        "part_number": line.part_number,
                        "normalized_part_number": _part_key(line.part_number),
                        "brand": order_brands.get((
                            _token(line.company_code), _token(line.order_branch_code),
                            _token(line.order_number), _token(line.line_number),
                        ), ""),
                        "invoiced_quantity": line.invoiced_quantity,
                        "source_line_amount": line.net_amount or Decimal("0"),
                        "allocated_revenue_eur": allocated,
                        "active": True,
                    })
                    allocated_total += allocated
                    counters["read"] += 1
                    if len(pending) >= cls.BATCH_SIZE:
                        cls._persist(pending, run, now, counters)
                        pending = []

            for line in links.iterator(chunk_size=10000):
                order_key = (
                    _token(line.company_code), _token(line.order_branch_code),
                    _token(line.order_number), _token(line.line_number),
                )
                explicit_brand = order_brands.get(order_key, "")
                if explicit_brand:
                    invoice_brands[(
                        _token(line.company_code), _token(line.invoice_number), _part_key(line.part_number)
                    )] = explicit_brand
                key = (_token(line.company_code), _token(line.invoice_number))
                if current_key is not None and key != current_key:
                    consume_invoice(current_key, invoice_lines)
                    invoice_lines = []
                current_key = key
                invoice_lines.append(line)
            if current_key is not None:
                consume_invoice(current_key, invoice_lines)
            if pending:
                cls._persist(pending, run, now, counters)
            cls._backfill_explicit_brands(invoice_brands, counters)

            with transaction.atomic():
                # Reconciliation snapshots are incremental. Existing invoiced history remains
                # active unless a source row is explicitly superseded by its stable identifier.
                counters["deactivated"] = 0
                counters["other_brand_backfilled"] = PartSaleDetail.objects.filter(
                    active=True, brand_group="Brand Not Available"
                ).update(brand="OTHER", brand_group="Other Brands", classification_status="Other Brand")
                warnings = []
                if counters["zero_value_invoice"]:
                    warnings.append(
                        f"{counters['zero_value_invoice']} invoices could not be allocated because their line total is zero."
                    )
                unclassified = PartSaleDetail.objects.filter(
                    active=True, synchronization_run=run
                ).exclude(classification_status="Classified").count()
                if unclassified:
                    warnings.append(f"{unclassified} invoiced part lines are not classified by the supplied reference.")
                run.status = "Completed with Warnings" if warnings else "Completed"
                run.data_through_date = PartSaleDetail.objects.filter(active=True).order_by(
                    "-business_date"
                ).values_list("business_date", flat=True).first()
                run.records_read = counters["read"]
                run.records_created = counters["created"]
                run.records_updated = counters["updated"]
                run.records_unchanged = counters["unchanged"]
                run.records_deactivated = counters["deactivated"]
                run.classified_records = PartSaleDetail.objects.filter(
                    active=True, classification_status="Classified"
                ).count()
                run.allocated_revenue_eur = allocated_total
                run.warnings_json = warnings
                run.completed_at = timezone.now()
                run.save()
            return run
        except Exception as exc:
            run.status = "Failed"
            run.error_message = str(exc)[:2000]
            run.completed_at = timezone.now()
            run.save(update_fields=["status", "error_message", "completed_at"])
            raise

    @classmethod
    def _persist(cls, payloads, run, now, counters):
        part_keys = {payload["normalized_part_number"] for payload in payloads if payload["normalized_part_number"]}
        classifications = {
            item.normalized_part_number: item
            for item in PartClassificationReference.objects.filter(
                active=True, classification_status="Classified",
                normalized_part_number__in=part_keys,
            ).select_related("major_class")
        }
        source_ids = {payload["source_record_id"] for payload in payloads}
        existing = {
            item.source_record_id: item
            for item in PartSaleDetail.objects.filter(source_record_id__in=source_ids)
        }
        creates = []
        updates = []
        fields = [
            "business_date", "company_code", "branch_code", "customer_code", "customer_name",
            "invoice_number", "part_number", "normalized_part_number", "brand", "brand_group", "major_class_code",
            "major_class_description", "minor_class", "ppc", "classification_status",
            "invoiced_quantity", "source_line_amount", "allocated_revenue_eur", "source_hash",
            "active", "synchronization_run", "source_last_seen_at",
        ]
        for payload in payloads:
            classification = classifications.get(payload["normalized_part_number"])
            source_brand = _text(payload.get("brand")).upper()
            if source_brand in {"CAT", "CATERPILLAR"} or (not source_brand and classification):
                brand = "CAT"
                brand_group = "CAT"
            elif source_brand:
                brand = source_brand
                brand_group = "Other Brands"
            else:
                brand = "OTHER"
                brand_group = "Other Brands"
            use_cat_classification = brand_group == "CAT" and classification is not None
            payload.update({
                "brand": brand,
                "brand_group": brand_group,
                "major_class_code": classification.major_class.code if use_cat_classification and classification.major_class else "",
                "major_class_description": classification.major_class.description if use_cat_classification and classification.major_class else "",
                "minor_class": classification.minor_class if use_cat_classification else "",
                "ppc": classification.ppc if use_cat_classification else "",
                "classification_status": "Classified" if use_cat_classification else (
                    "Not Classified" if brand_group == "CAT" else "Other Brand"
                ),
            })
            source_hash = _hash(payload)
            item = existing.get(payload["source_record_id"])
            if item is None:
                creates.append(PartSaleDetail(
                    source_hash=source_hash, synchronization_run=run, source_last_seen_at=now, **payload
                ))
                counters["created"] += 1
            else:
                changed = item.source_hash != source_hash or not item.active
                for field, value in payload.items():
                    setattr(item, field, value)
                item.source_hash = source_hash
                item.synchronization_run = run
                item.source_last_seen_at = now
                updates.append(item)
                counters["updated" if changed else "unchanged"] += 1
        with transaction.atomic():
            PartSaleDetail.objects.bulk_create(creates, batch_size=cls.BATCH_SIZE)
            PartSaleDetail.objects.bulk_update(updates, fields, batch_size=cls.UPDATE_BATCH_SIZE)

    @classmethod
    def _backfill_explicit_brands(cls, invoice_brands, counters):
        if not invoice_brands:
            return
        updates = []
        invoice_numbers = sorted({key[1] for key in invoice_brands})
        for offset in range(0, len(invoice_numbers), 500):
            sales = list(PartSaleDetail.objects.filter(
                active=True, invoice_number__in=invoice_numbers[offset:offset + 500]
            ))
            part_keys = {item.normalized_part_number for item in sales}
            classifications = {}
            part_key_list = sorted(part_keys)
            for part_offset in range(0, len(part_key_list), 500):
                for classification in PartClassificationReference.objects.filter(
                    active=True, classification_status="Classified",
                    normalized_part_number__in=part_key_list[part_offset:part_offset + 500],
                ).select_related("major_class"):
                    classifications[classification.normalized_part_number] = classification
            for item in sales:
                source_brand = invoice_brands.get((
                    _token(item.company_code), _token(item.invoice_number), item.normalized_part_number
                ))
                if not source_brand:
                    continue
                normalized_brand = _text(source_brand).upper()
                classification = classifications.get(item.normalized_part_number)
                if normalized_brand in {"CAT", "CATERPILLAR"}:
                    item.brand = "CAT"
                    item.brand_group = "CAT"
                    item.major_class_code = classification.major_class.code if classification and classification.major_class else ""
                    item.major_class_description = classification.major_class.description if classification and classification.major_class else ""
                    item.minor_class = classification.minor_class if classification else ""
                    item.ppc = classification.ppc if classification else ""
                    item.classification_status = "Classified" if classification else "Not Classified"
                else:
                    item.brand = normalized_brand
                    item.brand_group = "Other Brands"
                    item.major_class_code = ""
                    item.major_class_description = ""
                    item.minor_class = ""
                    item.ppc = ""
                    item.classification_status = "Other Brand"
                updates.append(item)
        if updates:
            PartSaleDetail.objects.bulk_update(
                updates,
                ["brand", "brand_group", "major_class_code", "major_class_description",
                 "minor_class", "ppc", "classification_status"],
                batch_size=cls.UPDATE_BATCH_SIZE,
            )
            counters["brand_backfilled"] += len(updates)


class PartsSalesDetailService:
    PAGE_SIZE = 50
    MAX_PAGE_SIZE = 150
    GROUP_FIELDS = {
        "major": ("brand_group", "major_class_code", "major_class_description"),
        "minor": ("brand_group", "major_class_code", "minor_class"),
        "ppc": ("brand_group", "major_class_code", "minor_class", "ppc"),
    }

    def __init__(self, user, params):
        self.user = user
        self.params = params

    def result(self):
        queryset = PartSaleDetail.objects.filter(active=True)
        if self.params.get("start_date"):
            queryset = queryset.filter(business_date__gte=self.params["start_date"])
        if self.params.get("end_date"):
            queryset = queryset.filter(business_date__lte=self.params["end_date"])
        account_scope = authorized_account_codes(self.user)
        if account_scope is not None:
            queryset = queryset.filter(customer_code__in=account_scope) if account_scope else queryset.none()
        customer_codes = {value for value in _text(self.params.get("customer_codes")).split(",") if value}
        if customer_codes:
            queryset = queryset.filter(customer_code__in=customer_codes)
        search = _text(self.params.get("search"))
        if search:
            queryset = queryset.filter(part_number__icontains=search)
        for parameter, field in (("major", "major_class_code"), ("minor", "minor_class"), ("ppc", "ppc")):
            if self.params.get(parameter):
                queryset = queryset.filter(**{field: self.params[parameter]})
        group_by = self.params.get("group_by") if self.params.get("group_by") in self.GROUP_FIELDS else "major"
        fields = self.GROUP_FIELDS[group_by]
        grouped = list(queryset.values(*fields).annotate(
            revenue_eur=Sum("allocated_revenue_eur"), line_count=Count("id"),
            part_count=Count("normalized_part_number", distinct=True),
        ).order_by("-revenue_eur"))
        page = max(1, int(self.params.get("page") or 1))
        page_size = min(self.MAX_PAGE_SIZE, max(1, int(self.params.get("page_size") or self.PAGE_SIZE)))
        offset = (page - 1) * page_size
        total_allocated = queryset.aggregate(value=Sum("allocated_revenue_eur"))["value"] or Decimal("0")
        classified = queryset.filter(classification_status="Classified").aggregate(
            value=Sum("allocated_revenue_eur")
        )["value"] or Decimal("0")
        other_brands = queryset.filter(brand_group="Other Brands").aggregate(
            value=Sum("allocated_revenue_eur")
        )["value"] or Decimal("0")
        certified = RevenueSourceSnapshot.objects.filter(active=True, division__iexact="MI", lob="PARTS")
        if self.params.get("start_date"):
            certified = certified.filter(business_date__gte=self.params["start_date"])
        if self.params.get("end_date"):
            certified = certified.filter(business_date__lte=self.params["end_date"])
        if account_scope is not None:
            certified = certified.filter(source_account_code__in=account_scope) if account_scope else certified.none()
        if customer_codes:
            certified = certified.filter(source_account_code__in=customer_codes)
        certified_total = certified.aggregate(value=Sum("revenue_eur"))["value"] or Decimal("0")
        last_run = PartsSalesSynchronizationRun.objects.filter(
            status__in=["Completed", "Completed with Warnings"]
        ).first()
        results = []
        for rank, row in enumerate(grouped[offset:offset + page_size], start=offset + 1):
            brand_group = row.get("brand_group") or "Brand Not Available"
            label = (
                row.get("major_class_description") or row.get("ppc") or row.get("minor_class")
                if brand_group == "CAT" else brand_group
            )
            results.append({
                "rank": rank,
                "brand_group": brand_group,
                "major_class": row.get("major_class_code") or None,
                "major_description": row.get("major_class_description") or None,
                "minor_class": row.get("minor_class") or None,
                "ppc": row.get("ppc") or None,
                "label": label,
                "revenue_eur": float(row["revenue_eur"] or 0),
                "line_count": row["line_count"],
                "part_count": row["part_count"],
            })
        return {
            "ready": bool(last_run),
            "freshness": {
                "data_through_date": last_run.data_through_date.isoformat() if last_run and last_run.data_through_date else None,
                "synchronized_at": last_run.completed_at if last_run else None,
                "status": last_run.status if last_run else "Not synchronized",
            },
            "context": {"group_by": group_by},
            "summary": {
                "certified_parts_revenue_eur": float(certified_total),
                "allocated_invoice_revenue_eur": float(total_allocated),
                "classified_revenue_eur": float(classified),
                "other_brands_revenue_eur": float(other_brands),
                "unlinked_revenue_eur": float(certified_total - total_allocated),
                "reconciliation_coverage_pct": float(total_allocated / certified_total * 100) if certified_total else None,
                "classification_coverage_pct": float(classified / total_allocated * 100) if total_allocated else None,
                "end_to_end_coverage_pct": float(classified / certified_total * 100) if certified_total else None,
                "line_count": queryset.count(),
            },
            "filter_options": {
                "major_classes": list(queryset.exclude(major_class_code="").values_list(
                    "major_class_code", flat=True
                ).order_by("major_class_code").distinct()),
                "minor_classes": list(queryset.exclude(minor_class="").values_list(
                    "minor_class", flat=True
                ).order_by("minor_class").distinct()),
                "ppcs": list(queryset.exclude(ppc="").values_list("ppc", flat=True).order_by("ppc").distinct()),
            },
            "pagination": {
                "page": page, "page_size": page_size, "count": len(grouped),
                "pages": (len(grouped) + page_size - 1) // page_size,
            },
            "results": results,
        }
