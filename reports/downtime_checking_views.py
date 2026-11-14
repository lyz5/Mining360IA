"""Configuration UI for the read-only YTD downtime quality check."""
import csv
import json

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .access_control import is_platform_admin
from .downtime_checking_rules import KINDS
from .downtime_checking_service import ACTIVE, ERRORS, enqueue, expire_stale, payload
from .downtime_checking_source import SourceCheckError
from .models import DowntimeCheckingFinding, DowntimeCheckingRun


def _allowed(request):
    return is_platform_admin(request.user)


def _json_body(request):
    try:
        value = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        value = {}
    return value if isinstance(value, dict) else {}


def _safe_int(value, default=1, minimum=1, maximum=100):
    try:
        return min(maximum, max(minimum, int(value)))
    except (TypeError, ValueError):
        return default


def _latest(year, *, completed_only=False):
    query = DowntimeCheckingRun.objects.filter(year=year)
    if completed_only:
        query = query.filter(status="completed")
    return query.order_by("-created_at", "-id").first()


def _finding_payload(item):
    return {
        "id": item.pk, "event_id": item.event_id, "rule_code": item.rule_code,
        "kind": item.kind, "kind_label": KINDS.get(item.kind, item.kind), "change": item.change,
        "changed_evidence": item.changed_evidence, "minesite": item.minesite,
        "serial_number": item.serial_number, "labour_type": item.labour_type,
        "description_cat": item.description_cat, "comment": item.comment,
        "downtime_hours": str(item.downtime_hours) if item.downtime_hours is not None else None,
        "title": item.title, "reason": item.reason, "recommendation": item.recommendation,
        "evidence": item.evidence, "previous_evidence": item.previous_evidence,
    }


def _filtered_findings(run, params):
    query = run.findings.all()
    kind = str(params.get("kind") or "").strip()
    if kind in KINDS:
        query = query.filter(kind=kind)
    change = str(params.get("change") or "open").strip()
    allowed_changes = {"all", "open", "new", "persistent", "resolved", "unverified"}
    if change not in allowed_changes:
        change = "open"
    if change == "open":
        query = query.filter(change__in=("new", "persistent", "unverified"))
    elif change != "all":
        query = query.filter(change=change)
    minesite = str(params.get("minesite") or "").strip()
    if minesite:
        query = query.filter(minesite=minesite)
    search = str(params.get("q") or "").strip()
    if search:
        query = query.filter(
            Q(event_id__icontains=search) | Q(labour_type__icontains=search) |
            Q(description_cat__icontains=search) | Q(serial_number__icontains=search) |
            Q(comment__icontains=search) | Q(title__icontains=search)
        )
    return query.order_by("minesite", "event_id", "rule_code", "id"), change


@login_required
@ensure_csrf_cookie
@require_GET
def page(request):
    if not _allowed(request):
        return HttpResponse("Administrator access required.", status=403)
    today = timezone.localdate()
    return render(request, "reports/downtime_checking.html", {
        "active_section": "downtime-checking", "ytd_year": today.year,
        "ytd_start": today.replace(month=1, day=1), "ytd_end": today,
    })


@login_required
@require_GET
def status_api(request):
    if not _allowed(request):
        return JsonResponse({"ok": False, "error": "Administrator access required."}, status=403)
    today = timezone.localdate()
    expire_stale(today.year)
    current = _latest(today.year)
    successful = _latest(today.year, completed_only=True)
    history = DowntimeCheckingRun.objects.filter(year=today.year).order_by("-created_at", "-id")[:12]
    return JsonResponse({"ok": True, "year": today.year, "current": payload(current),
                         "successful": payload(successful), "history": [payload(item) for item in history]})


@login_required
@require_POST
def recheck_api(request):
    if not _allowed(request):
        return JsonResponse({"ok": False, "error": "Administrator access required."}, status=403)
    # The endpoint deliberately ignores client-provided period, browser and SQL
    # values.  It always performs the server-defined current YTD check.
    try:
        run, created = enqueue(request.user)
    except SourceCheckError as error:
        return JsonResponse({"ok": False, "error": ERRORS.get(error.code, ERRORS["check_failed"])}, status=409)
    return JsonResponse({"ok": True, "created": created, "run": payload(run)}, status=202 if created else 409)


@login_required
@require_GET
def results_api(request):
    if not _allowed(request):
        return JsonResponse({"ok": False, "error": "Administrator access required."}, status=403)
    today = timezone.localdate()
    run_id = str(request.GET.get("run") or "").strip()
    run = get_object_or_404(DowntimeCheckingRun, pk=run_id, year=today.year, status="completed") if run_id else _latest(today.year, completed_only=True)
    if not run:
        return JsonResponse({"ok": True, "run": None, "count": 0, "results": [], "sites": [], "page": 1, "pages": 0})
    query, change = _filtered_findings(run, request.GET)
    paginator = Paginator(query, _safe_int(request.GET.get("page_size"), 50, 10, 100))
    page_obj = paginator.get_page(_safe_int(request.GET.get("page"), 1, 1, max(1, paginator.num_pages)))
    sites = list(run.findings.exclude(minesite="").order_by("minesite").values_list("minesite", flat=True).distinct())
    return JsonResponse({"ok": True, "run": payload(run), "count": paginator.count, "sites": sites,
                         "selected": {"kind": request.GET.get("kind", ""), "change": change, "minesite": request.GET.get("minesite", ""), "q": request.GET.get("q", "")},
                         "page": page_obj.number, "pages": paginator.num_pages, "page_size": paginator.per_page,
                         "results": [_finding_payload(item) for item in page_obj.object_list]})


def _safe_csv(value):
    text = str(value or "")
    return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text


@login_required
@require_GET
def export_api(request):
    if not _allowed(request):
        return JsonResponse({"ok": False, "error": "Administrator access required."}, status=403)
    today = timezone.localdate()
    run_id = str(request.GET.get("run") or "").strip()
    run = get_object_or_404(DowntimeCheckingRun, pk=run_id, year=today.year, status="completed") if run_id else _latest(today.year, completed_only=True)
    if not run:
        return JsonResponse({"ok": False, "error": "No completed YTD check is available."}, status=404)
    rows, _ = _filtered_findings(run, request.GET)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="downtime-checking-ytd-{run.year}-{run.pk}.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(["Event ID", "MineSite", "Serial number", "Labour Type", "Description CAT", "Issue type", "Check state", "Issue", "Reason", "Recommendation", "Comment", "Downtime hours"])
    for item in rows.iterator(chunk_size=500):
        writer.writerow([_safe_csv(value) for value in (item.event_id, item.minesite, item.serial_number, item.labour_type,
            item.description_cat, KINDS.get(item.kind, item.kind), item.change, item.title, item.reason,
            item.recommendation, item.comment, item.downtime_hours)])
    return response
