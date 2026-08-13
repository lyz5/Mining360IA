from __future__ import annotations

import csv
import io
import json
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .access_control import is_platform_admin
from .downtime_mapping_check_service import (
    DowntimeMappingCheckError,
    enqueue_run,
    estimate_run,
    feature_enabled,
    run_payload,
)
from .models import (
    DescriptionCATReference,
    DowntimeMappingCheckItem,
    DowntimeMappingCheckRun,
    DowntimeMappingReviewDecision,
)


def _body(request):
    try:
        value = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        value = {}
    return value if isinstance(value, dict) else {}


def _dates(payload):
    start = parse_date(str(payload.get("start_date") or ""))
    end = parse_date(str(payload.get("end_date") or ""))
    if not start or not end:
        raise DowntimeMappingCheckError("Start Date and End Date are required.")
    return start, end


def _allowed(request, *, admin=False):
    if not feature_enabled(request.user):
        return False
    return is_platform_admin(request.user) if admin else True


@login_required
@require_GET
def page(request):
    if not _allowed(request):
        return HttpResponse("Downtime Mapping Check is not enabled for your account.", status=403)
    return render(request, "reports/downtime_mapping_check.html", {
        "active_section": "data",
        "validated_taxonomy_count": DescriptionCATReference.objects.filter(active=True, validation_status="Validated").count(),
        "writeback_enabled": str(getattr(settings, "ENABLE_DOWNTIME_MAPPING_WRITEBACK", "Disabled")).casefold() != "disabled",
    })


@login_required
@require_POST
def preview_api(request):
    if not _allowed(request, admin=True):
        return JsonResponse({"ok": False, "error": "Admin access required."}, status=403)
    payload = _body(request)
    try:
        start, end = _dates(payload)
        result = estimate_run(start, end, payload.get("filters") or {}, payload.get("mode") or "full")
    except DowntimeMappingCheckError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    return JsonResponse({"ok": True, "preview": result})


@login_required
@require_http_methods(["GET", "POST"])
def runs_api(request):
    if not _allowed(request):
        return JsonResponse({"ok": False, "error": "Access denied."}, status=403)
    if request.method == "GET":
        runs = DowntimeMappingCheckRun.objects.select_related("created_by")[:50]
        return JsonResponse({"ok": True, "runs": [run_payload(run) for run in runs]})
    if not _allowed(request, admin=True):
        return JsonResponse({"ok": False, "error": "Admin access required."}, status=403)
    if not DescriptionCATReference.objects.filter(active=True, validation_status="Validated").exists():
        return JsonResponse({"ok": False, "error": "Validate at least one Description CAT reference before starting a check."}, status=409)
    payload = _body(request)
    try:
        start, end = _dates(payload)
        preview = estimate_run(start, end, payload.get("filters") or {}, payload.get("mode") or "full")
        maximum = int(getattr(settings, "DOWNTIME_MAPPING_MAX_ROWS_PER_RUN", 5000))
        if preview["total_rows"] > maximum:
            raise DowntimeMappingCheckError(f"The selection contains {preview['total_rows']} rows. Narrow the filters to {maximum} rows or fewer.")
        maximum_cost = float(getattr(settings, "DOWNTIME_MAPPING_MAX_ESTIMATED_COST", 20))
        if preview["estimated_cost"] > maximum_cost:
            raise DowntimeMappingCheckError(f"The estimated API cost exceeds the configured ${maximum_cost:.2f} run limit.")
        if not preview["total_rows"]:
            raise DowntimeMappingCheckError("No downtime events were found for the selected date range and filters.")
        run = DowntimeMappingCheckRun.objects.create(
            created_by=request.user, start_date=start, end_date=end, filters_json=payload.get("filters") or {},
            execution_mode=payload.get("mode") or "full", processing_method=payload.get("processing_method") or "standard",
            total_rows=preview["total_rows"], estimated_tokens=preview["estimated_tokens"], estimated_cost=preview["estimated_cost"],
            comment_coverage=(preview["rows_with_comment"] / preview["total_rows"] * 100 if preview["total_rows"] else 0), status="Queued",
        )
        enqueue_run(run)
    except DowntimeMappingCheckError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    return JsonResponse({"ok": True, "run": run_payload(run)}, status=201)


@login_required
@require_GET
def run_api(request, run_id):
    if not _allowed(request):
        return JsonResponse({"ok": False, "error": "Access denied."}, status=403)
    run = get_object_or_404(DowntimeMappingCheckRun, pk=run_id)
    return JsonResponse({"ok": True, "run": run_payload(run)})


def _item_payload(item):
    return {
        "id": item.id, "event_id": item.downtime_event_id, "date": item.event_start.isoformat() if item.event_start else None,
        "minesite": item.minesite, "serial_number": item.serial_number, "model": item.model, "labour_type": item.labour_type,
        "current_description_cat": item.current_description_cat,
        "recommended_description_cat": item.recommended_description_cat.display_name if item.recommended_description_cat else "",
        "recommended_description_cat_id": item.recommended_description_cat_id, "status": item.mapping_status,
        "confidence": item.confidence, "comment_quality": item.comment_quality, "comment": item.comment_snapshot,
        "reason": item.reason, "evidence": item.evidence_phrases_json, "detected_information": item.detected_information_json,
        "alternatives": item.alternative_candidates_json, "candidates": item.candidate_list_json,
        "requires_review": item.requires_review, "review_status": item.review_status, "review_notes": item.review_notes,
    }


@login_required
@require_GET
def items_api(request, run_id):
    if not _allowed(request):
        return JsonResponse({"ok": False, "error": "Access denied."}, status=403)
    run = get_object_or_404(DowntimeMappingCheckRun, pk=run_id)
    queryset = run.items.select_related("recommended_description_cat")
    status = request.GET.get("status", "").strip()
    if status:
        queryset = queryset.filter(mapping_status=status)
    query = request.GET.get("q", "").strip()
    if query:
        queryset = queryset.filter(Q(downtime_event_id__icontains=query) | Q(labour_type__icontains=query) | Q(current_description_cat__icontains=query) | Q(comment_snapshot__icontains=query) | Q(serial_number__icontains=query))
    try:
        page = max(1, int(request.GET.get("page") or 1))
        page_size = min(100, max(10, int(request.GET.get("page_size") or 50)))
    except ValueError:
        return JsonResponse({"ok": False, "error": "Invalid pagination."}, status=400)
    count = queryset.count()
    items = queryset[(page - 1) * page_size:page * page_size]
    return JsonResponse({"ok": True, "count": count, "page": page, "page_size": page_size, "results": [_item_payload(item) for item in items]})


@login_required
@require_POST
def review_api(request, item_id):
    if not _allowed(request, admin=True):
        return JsonResponse({"ok": False, "error": "Review permission required."}, status=403)
    item = get_object_or_404(DowntimeMappingCheckItem.objects.select_related("recommended_description_cat"), pk=item_id)
    payload = _body(request)
    decision = str(payload.get("decision") or "")
    allowed = dict(DowntimeMappingReviewDecision.DECISIONS)
    if decision not in allowed:
        return JsonResponse({"ok": False, "error": "Invalid review decision."}, status=400)
    selected = None
    selected_id = payload.get("description_cat_id")
    if selected_id:
        selected = get_object_or_404(DescriptionCATReference, pk=selected_id, active=True, validation_status="Validated")
    if decision == "Approve AI Recommendation" and not item.recommended_description_cat:
        return JsonResponse({"ok": False, "error": "No AI recommendation is available."}, status=400)
    if decision == "Select Another Description CAT" and selected is None:
        return JsonResponse({"ok": False, "error": "Select an approved Description CAT."}, status=400)
    with transaction.atomic():
        DowntimeMappingReviewDecision.objects.create(
            check_item=item, original_current_description_cat=item.current_description_cat,
            ai_recommended_description_cat=item.recommended_description_cat.display_name if item.recommended_description_cat else "",
            reviewer_selected_description_cat=selected, decision=decision, notes=str(payload.get("notes") or ""), reviewer=request.user,
        )
        mapping = {
            "Approve Current": ("Approved Current", None),
            "Approve AI Recommendation": ("Approved Recommendation", item.recommended_description_cat),
            "Select Another Description CAT": ("Alternative Selected", selected),
            "Mark Ambiguous": ("Ambiguous", None),
            "Mark Insufficient Evidence": ("Insufficient Evidence", None),
            "Reject AI Result": ("Rejected", None),
        }
        item.review_status, item.approved_description_cat = mapping[decision]
        item.reviewed_by = request.user
        item.reviewed_at = timezone.now()
        item.review_notes = str(payload.get("notes") or "")
        item.save(update_fields=["review_status", "approved_description_cat", "reviewed_by", "reviewed_at", "review_notes", "updated_at"])
    return JsonResponse({"ok": True, "item": _item_payload(item)})


@login_required
@require_POST
def cancel_api(request, run_id):
    if not _allowed(request, admin=True):
        return JsonResponse({"ok": False, "error": "Cancel permission required."}, status=403)
    run = get_object_or_404(DowntimeMappingCheckRun, pk=run_id)
    run.cancellation_requested = True
    if run.status == "Queued":
        run.status = "Cancelled"
    run.save(update_fields=["cancellation_requested", "status", "updated_at"])
    return JsonResponse({"ok": True, "run": run_payload(run)})


@login_required
@require_GET
def export_api(request, run_id, file_type="csv"):
    if not _allowed(request):
        return JsonResponse({"ok": False, "error": "Export permission required."}, status=403)
    run = get_object_or_404(DowntimeMappingCheckRun, pk=run_id)
    headers = ["Event ID", "Date", "MineSite", "Serial Number", "Model", "Labour Type", "Current Description CAT", "Recommended Description CAT", "Mapping Status", "Confidence", "Comment Quality", "Comment", "Reason", "Evidence", "Review Decision", "Reviewer", "Applied"]
    rows = [[item.downtime_event_id, item.event_start.isoformat() if item.event_start else "", item.minesite, item.serial_number, item.model, item.labour_type, item.current_description_cat, item.recommended_description_cat.display_name if item.recommended_description_cat else "", item.mapping_status, item.confidence, item.comment_quality, item.comment_snapshot, item.reason, " | ".join(item.evidence_phrases_json), item.review_status, item.reviewed_by.username if item.reviewed_by else "", item.applied] for item in run.items.select_related("recommended_description_cat", "reviewed_by")]
    file_type = file_type.casefold()
    if file_type == "json":
        response = JsonResponse({"run": run_payload(run), "columns": headers, "results": [dict(zip(headers, row)) for row in rows]}, json_dumps_params={"ensure_ascii": False})
        response["Content-Disposition"] = f'attachment; filename="downtime-mapping-{run.pk}.json"'
        return response
    if file_type == "xlsx":
        from openpyxl import Workbook
        workbook = Workbook(write_only=True)
        sheet = workbook.create_sheet("Mapping audit")
        sheet.append(headers)
        for row in rows:
            sheet.append(row)
        output = io.BytesIO()
        workbook.save(output)
        response = HttpResponse(output.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        response["Content-Disposition"] = f'attachment; filename="downtime-mapping-{run.pk}.xlsx"'
        return response
    if file_type != "csv":
        return JsonResponse({"ok": False, "error": "Supported exports are csv, xlsx and json."}, status=400)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="downtime-mapping-{run.pk}.csv"'
    writer = csv.writer(response)
    writer.writerow(headers)
    writer.writerows(rows)
    return response


@login_required
@require_GET
def taxonomy_api(request):
    if not _allowed(request):
        return JsonResponse({"ok": False, "error": "Access denied."}, status=403)
    items = DescriptionCATReference.objects.filter(active=True, validation_status="Validated").values("id", "code", "display_name", "definition")
    return JsonResponse({"ok": True, "results": list(items)})
