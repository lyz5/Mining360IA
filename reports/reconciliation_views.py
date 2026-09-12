import csv
from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from .models import (
    ReconciliationBufferSyncRun,
    ReconciliationMatch,
    ReconciliationMatchAccountingEntry,
    ReconciliationOrderHeader,
    ReconciliationOrderLine,
    ReconciliationRun,
    ReconciliationSourceSnapshot,
)
from .reconciliation_buffer_service import SemanticReconciliationBufferService


def _iso_date(value):
    try:
        return date.fromisoformat(str(value or "").strip())
    except ValueError:
        return None


def _is_platform_admin(user):
    profile = getattr(user, "platformuser", None)
    return bool(profile and profile.is_platform_admin)


def _can_review(user):
    return (
        user.is_superuser
        or _is_platform_admin(user)
        or user.has_perm("reports.review_reconciliation")
    )


def _can_run(user):
    return (
        user.is_superuser
        or _is_platform_admin(user)
        or user.has_perm("reports.run_reconciliation")
    )


def _require_review(user):
    if not _can_review(user):
        raise PermissionDenied("Invoice Tracking access required.")


def _sync_payload(run):
    if not run:
        return None
    return {
        "id": str(run.pk), "status": run.status, "progress_percent": run.progress_percent,
        "stage_code": run.stage_code, "stage_label": run.stage_label,
        "source_status": run.source_status_json, "warnings": run.warnings_json,
        "errors": run.errors_json, "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


def _matches(request):
    run = ReconciliationRun.objects.order_by("-created_at").first()
    queryset = ReconciliationMatch.objects.none()
    if run:
        queryset = ReconciliationMatch.objects.filter(run=run).select_related(
            "delivery_invoice_link", "order_line", "invoice_header"
        ).annotate(
            accounting_total=Sum("accounting_links__accounting_entry__consolidated_amount"),
            accounting_entry_count=Count("accounting_links", distinct=True),
        )
        status = str(request.GET.get("status") or "").strip()
        search = str(request.GET.get("search") or "").strip()
        company = str(request.GET.get("company") or "").strip()
        date_from = _iso_date(request.GET.get("date_from"))
        date_to = _iso_date(request.GET.get("date_to"))
        if status:
            queryset = queryset.filter(status=status)
        if company:
            queryset = queryset.filter(delivery_invoice_link__company_code=company)
        if date_from:
            queryset = queryset.filter(order_line__order_date__gte=date_from)
        if date_to:
            queryset = queryset.filter(order_line__order_date__lte=date_to)
        if search:
            queryset = queryset.filter(
                Q(delivery_invoice_link__order_number__icontains=search)
                | Q(delivery_invoice_link__invoice_number__icontains=search)
                | Q(delivery_invoice_link__delivery_number__icontains=search)
                | Q(delivery_invoice_link__customer_number__icontains=search)
                | Q(delivery_invoice_link__part_number__icontains=search)
            )
        sort = str(request.GET.get("sort") or "invoice").strip()
        ordering = {
            "invoice": ("delivery_invoice_link__invoice_number", "delivery_invoice_link__order_number"),
            "order": ("delivery_invoice_link__order_number", "delivery_invoice_link__line_number"),
            "status": ("status", "delivery_invoice_link__invoice_number"),
            "company": ("delivery_invoice_link__company_code", "delivery_invoice_link__invoice_number"),
            "-amount": ("-accounting_total", "delivery_invoice_link__invoice_number"),
        }.get(sort, ("delivery_invoice_link__invoice_number",))
        queryset = queryset.order_by(*ordering)
    return run, queryset


def _serialize_match(match):
    link = match.delivery_invoice_link
    order = match.order_line
    invoice = match.invoice_header
    return {
        "id": match.pk,
        "status": match.status,
        "confidence": str(match.confidence_score),
        "company": link.company_code,
        "customer": link.customer_number,
        "order_number": link.order_number,
        "order_line": link.line_number,
        "order_date": order.order_date.isoformat() if order and order.order_date else None,
        "part_number": link.part_number,
        "delivery_number": link.delivery_number,
        "invoice_number": link.invoice_number,
        "invoice_date": invoice.invoice_date.isoformat() if invoice and invoice.invoice_date else None,
        "invoice_status": invoice.invoice_status if invoice else None,
        "ordered_quantity": str(order.ordered_quantity) if order and order.ordered_quantity is not None else None,
        "delivered_quantity": str(link.delivered_quantity) if link.delivered_quantity is not None else None,
        "invoiced_quantity": str(link.invoiced_quantity) if link.invoiced_quantity is not None else None,
        "line_amount": str(link.net_amount) if link.net_amount is not None else None,
        "accounting_amount": str(match.accounting_total) if match.accounting_total is not None else None,
        "accounting_entry_count": match.accounting_entry_count,
        "cancellation_invoice": link.cancellation_invoice_number,
        "warnings": match.warnings_json,
        "matched_by": match.matched_by_json,
    }


ORDER_BILLING_STATUSES = (
    "INVOICED", "PARTIALLY_INVOICED", "NOT_INVOICED", "TO_INVESTIGATE", "NOT_DELIVERED",
)


def _order_billing_status(order, *, has_accounting, has_commercial_invoice):
    delivered = order.current_delivered_quantity or Decimal("0")
    invoiced = order.current_invoiced_quantity or Decimal("0")
    ordered = order.ordered_quantity
    if delivered <= 0:
        return "NOT_DELIVERED"
    if has_accounting:
        if ordered is not None and invoiced < ordered:
            return "PARTIALLY_INVOICED"
        return "INVOICED"
    if invoiced > 0 or has_commercial_invoice:
        return "TO_INVESTIGATE"
    return "NOT_INVOICED"


def _order_lines(request):
    run = ReconciliationRun.objects.order_by("-created_at").first()
    queryset = ReconciliationOrderLine.objects.none()
    if not run:
        return run, queryset
    queryset = ReconciliationOrderLine.objects.filter(snapshot=run.order_snapshot).select_related("order_header")
    search = str(request.GET.get("search") or "").strip()
    company = str(request.GET.get("company") or "").strip()
    status = str(request.GET.get("status") or "").strip()
    date_from = _iso_date(request.GET.get("date_from"))
    date_to = _iso_date(request.GET.get("date_to"))
    if search:
        queryset = queryset.filter(
            Q(order_number__icontains=search) | Q(line_number__icontains=search)
            | Q(customer_number__icontains=search) | Q(customer_name__icontains=search)
            | Q(order_header__customer_name__icontains=search) | Q(part_number__icontains=search)
        )
    if company:
        queryset = queryset.filter(company_code=company)
    if date_from:
        queryset = queryset.filter(order_date__gte=date_from)
    if date_to:
        queryset = queryset.filter(order_date__lte=date_to)
    if status in ORDER_BILLING_STATUSES:
        queryset = queryset.filter(billing_status=status)
    header_customer = str(request.GET.get("header_customer") or "").strip()
    if header_customer:
        queryset = queryset.filter(
            Q(customer_name__icontains=header_customer)
            | Q(order_header__customer_name__icontains=header_customer)
        )
    header_filters = {
        "order_header__order_type": str(request.GET.get("header_order_type") or "").strip(),
        "order_header__order_status": str(request.GET.get("header_order_status") or "").strip(),
        "order_header__invoicing_status": str(request.GET.get("header_invoicing_status") or "").strip(),
        "order_header__transport": str(request.GET.get("header_transport") or "").strip(),
        "order_header__urgency": str(request.GET.get("header_urgency") or "").strip(),
    }
    header_filters = {key: value for key, value in header_filters.items() if value}
    if header_filters:
        queryset = queryset.filter(**header_filters)
    ordering = {
        "order": ("-order_date", "order_number", "line_number"),
        "status": ("status", "-order_date"),
        "company": ("company_code", "-order_date"),
        "-amount": ("-net_amount", "-order_date"),
    }.get(str(request.GET.get("sort") or "order"), ("-order_date", "order_number", "line_number"))
    return run, queryset.order_by(*ordering)


def _header_snapshot(run):
    if not run:
        return None
    sync_prefix = run.order_snapshot.source_version.rsplit(":", 1)[0]
    return ReconciliationSourceSnapshot.objects.filter(
        source_kind="ORDER_HEADERS", source_version=f"{sync_prefix}:ORDER_HEADERS",
        status__in=["Ready", "Ready with Warnings"],
    ).first()


def _order_page_context(run, orders):
    order_ids = [order.pk for order in orders]
    matches_by_order = defaultdict(list)
    matches = ReconciliationMatch.objects.filter(run=run, order_line_id__in=order_ids).select_related(
        "delivery_invoice_link", "invoice_header"
    ).prefetch_related("accounting_entries")
    for match in matches:
        matches_by_order[match.order_line_id].append(match)

    header_by_key = {
        (order.company_code, order.branch_code, order.order_number): order.order_header
        for order in orders if order.order_header_id
    }
    header_snapshot = _header_snapshot(run)
    if header_snapshot and any(not order.order_header_id for order in orders):
        lookup = Q()
        for order in orders:
            lookup |= Q(company_code=order.company_code, order_number=order.order_number)
        headers = ReconciliationOrderHeader.objects.filter(snapshot=header_snapshot).filter(lookup)
        for header in headers:
            header_by_key[(header.company_code, header.branch_code, header.order_number)] = header
    return matches_by_order, header_by_key


def _serialize_order(order, matches, header):
    invoices = []
    deliveries = []
    invoice_dates = []
    accounting_entries = {}
    warnings = []
    for match in matches:
        link = match.delivery_invoice_link
        if link.invoice_number and not link.cancellation_invoice_number:
            invoices.append(link.invoice_number)
        if link.delivery_number:
            deliveries.append(link.delivery_number)
        if match.invoice_header and match.invoice_header.invoice_date:
            invoice_dates.append(match.invoice_header.invoice_date.isoformat())
        for entry in match.accounting_entries.all():
            accounting_entries[entry.pk] = entry.consolidated_amount
        warnings.extend(match.warnings_json or [])
    accounting_amounts = [value for value in accounting_entries.values() if value is not None]
    accounting_total = sum(accounting_amounts, Decimal("0")) if accounting_amounts else None
    has_accounting = order.ca_combine_present or bool(accounting_entries)
    has_commercial_invoice = any(
        match.invoice_header_id and match.status != "CANCELLED" for match in matches
    )
    billing_status = order.billing_status or _order_billing_status(
        order, has_accounting=has_accounting, has_commercial_invoice=has_commercial_invoice,
    )
    reason = {
        "INVOICED": "Invoice confirmed in CA Combine",
        "PARTIALLY_INVOICED": "CA Combine found; remaining quantity is not fully invoiced",
        "NOT_INVOICED": "Delivered quantity found without a CA Combine invoice",
        "TO_INVESTIGATE": "Source indicates invoicing but no CA Combine entry was matched",
        "NOT_DELIVERED": "No delivered quantity is currently recorded",
    }[billing_status]
    return {
        "id": order.pk, "view": "orders", "billing_status": billing_status,
        "status": billing_status, "operational_status": order.status,
        "company": order.company_code, "branch": order.branch_code,
        "customer": (header.customer_name if header else "") or order.customer_name or order.customer_number,
        "customer_name": (header.customer_name if header else "") or order.customer_name or None,
        "customer_number": order.customer_number,
        "order_number": order.order_number, "order_line": order.line_number,
        "order_date": order.order_date.isoformat() if order.order_date else None,
        "eta": header.eta.isoformat() if header and header.eta else None,
        "order_type": header.order_type if header else None,
        "urgency": header.urgency if header else None,
        "transport": header.transport if header else None,
        "order_description": header.description if header else None,
        "header_invoicing_status": header.invoicing_status if header else None,
        "header_order_status": header.order_status if header else None,
        "part_number": order.part_number,
        "delivery_number": ", ".join(sorted(set(deliveries))),
        "invoice_number": ", ".join(sorted(set(invoices))),
        "invoice_date": max(invoice_dates) if invoice_dates else None,
        "ordered_quantity": str(order.ordered_quantity) if order.ordered_quantity is not None else None,
        "delivered_quantity": str(order.current_delivered_quantity) if order.current_delivered_quantity is not None else None,
        "invoiced_quantity": str(order.current_invoiced_quantity) if order.current_invoiced_quantity is not None else None,
        "line_amount": str(order.net_amount) if order.net_amount is not None else None,
        "accounting_amount": str(accounting_total) if accounting_total is not None else None,
        "accounting_entry_count": len(accounting_entries), "ca_combine_present": has_accounting,
        "warnings": sorted(set(warnings)), "control_reason": reason,
    }


def _header_filter_options(run):
    snapshot = _header_snapshot(run)
    if not snapshot:
        return {}
    cache_key = f"invoice-tracking:order-header-filters:{snapshot.pk}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    base = ReconciliationOrderHeader.objects.filter(snapshot=snapshot)
    fields = ("order_type", "order_status", "invoicing_status", "transport", "urgency")
    options = {
        field: list(base.exclude(**{field: ""}).order_by(field).values_list(field, flat=True).distinct())
        for field in fields
    }
    cache.set(cache_key, options, 300)
    return options


@login_required
def invoice_tracking(request):
    _require_review(request.user)
    return render(request, "reports/invoice_tracking_detailed.html", {
        "active_section": "invoice-tracking",
        "can_run": _can_run(request.user),
        "sidebar_stats": [],
    })


@login_required
@require_GET
def overview_api(request):
    _require_review(request.user)
    sync = ReconciliationBufferSyncRun.objects.order_by("-created_at").first()
    run = ReconciliationRun.objects.order_by("-created_at").first()
    summary = run.summary_json if run else {}
    return JsonResponse({
        "ok": True,
        "sync": _sync_payload(sync),
        "reconciliation": None if not run else {
            "id": str(run.pk), "status": run.status, "rule_version": run.rule_version,
            "summary": summary, "warnings": run.warnings_json,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        },
        "can_run": _can_run(request.user),
    })


@login_required
@require_POST
def synchronization_api(request):
    if not _can_run(request.user):
        raise PermissionDenied("Invoice Tracking synchronization permission required.")
    active = ReconciliationBufferSyncRun.objects.filter(status__in=["Queued", "Running"]).order_by("-created_at").first()
    if active:
        return JsonResponse({"ok": True, "reused": True, "sync": _sync_payload(active)})
    service = SemanticReconciliationBufferService(request.user)
    run = service.queue()
    service.start_background(run)
    return JsonResponse({
        "ok": True, "reused": False, "sync": _sync_payload(run),
        "status_url": reverse("invoice-tracking-sync-status-api", args=[run.pk]),
    }, status=202)


@login_required
@require_GET
def synchronization_status_api(request, run_id):
    _require_review(request.user)
    run = ReconciliationBufferSyncRun.objects.filter(pk=run_id).first()
    if not run:
        return JsonResponse({"ok": False, "error": "Synchronization not found."}, status=404)
    return JsonResponse({"ok": True, "sync": _sync_payload(run)})


@login_required
@require_GET
def rows_api(request):
    _require_review(request.user)
    view = str(request.GET.get("view") or "orders").strip()
    run, queryset = _order_lines(request) if view == "orders" else _matches(request)
    try:
        requested_page_size = int(request.GET.get("page_size") or 50)
    except (TypeError, ValueError):
        requested_page_size = 50
    page_size = min(max(requested_page_size, 10), 200)
    page = Paginator(queryset, page_size).get_page(request.GET.get("page") or 1)
    companies, statuses = [], []
    header_filters = {}
    if run and view == "orders":
        base = ReconciliationOrderLine.objects.filter(snapshot=run.order_snapshot)
        companies = list(base.order_by("company_code").values_list("company_code", flat=True).distinct())
        statuses = list(ORDER_BILLING_STATUSES)
        matches_by_order, header_by_key = _order_page_context(run, page.object_list)
        results = [
            _serialize_order(
                order,
                matches_by_order.get(order.pk, []),
                header_by_key.get((order.company_code, order.branch_code, order.order_number)),
            )
            for order in page.object_list
        ]
        header_filters = _header_filter_options(run)
    elif run:
        base = ReconciliationMatch.objects.filter(run=run)
        companies = list(base.order_by("delivery_invoice_link__company_code").values_list(
            "delivery_invoice_link__company_code", flat=True
        ).distinct())
        statuses = list(base.order_by("status").values_list("status", flat=True).distinct())
        results = [_serialize_match(item) for item in page.object_list]
    else:
        results = []
    return JsonResponse({
        "ok": True,
        "view": view,
        "run_id": str(run.pk) if run else None,
        "count": page.paginator.count,
        "page": page.number,
        "pages": page.paginator.num_pages,
        "results": results,
        "filters": {"companies": companies, "statuses": statuses, "order_headers": header_filters},
    })


@login_required
@require_GET
def export_csv(request):
    _require_review(request.user)
    view = str(request.GET.get("view") or "orders").strip()
    run, queryset = _order_lines(request) if view == "orders" else _matches(request)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f"attachment; filename=invoice_tracking_{view}.csv"
    writer = csv.writer(response)
    if view == "orders":
        fields = ["billing_status", "operational_status", "company", "branch", "customer_name", "customer_number", "order_number", "order_line", "order_date", "eta", "order_type", "urgency", "transport", "part_number", "ordered_quantity", "delivered_quantity", "invoiced_quantity", "ca_combine_present", "invoice_number", "invoice_date", "line_amount", "accounting_amount", "control_reason"]
        writer.writerow(fields)
        batch_size = 500
        paginator = Paginator(queryset, batch_size)
        for page_number in paginator.page_range:
            orders = list(paginator.page(page_number).object_list)
            matches_by_order, header_by_key = _order_page_context(run, orders)
            for order in orders:
                row = _serialize_order(order, matches_by_order.get(order.pk, []), header_by_key.get((order.company_code, order.branch_code, order.order_number)))
                writer.writerow([row.get(field) for field in fields])
        return response
    fields = ["status", "company", "customer", "order_number", "order_line", "part_number", "delivery_number", "invoice_number", "invoice_date", "ordered_quantity", "delivered_quantity", "invoiced_quantity", "line_amount", "accounting_amount", "accounting_entry_count", "cancellation_invoice"]
    writer.writerow(fields)
    for match in queryset.iterator(chunk_size=1000):
        row = _serialize_match(match)
        writer.writerow([row.get(field) for field in fields])
    return response
