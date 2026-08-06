from __future__ import annotations

import json
import logging
from functools import wraps

from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from .access_control import is_platform_admin

from .availability_diagnostics_service import (
    build_availability_diagnostics_dax,
    parse_availability_diagnostics_rows,
)

from .downtime_context_service import (
    back_explorer,
    get_user_session,
    open_explorer,
    reset_explorer,
    select_dimension,
    serialize_session,
)
from .downtime_explorer_service import (
    initial_payload,
    load_breakdown,
    load_comments,
    load_equipment,
    load_events,
    load_repeated_failures,
    load_summary,
    load_smcs_breakdown,
    navigation_payload,
    run_comment_analysis,
    suggested_actions,
)
from .downtime_query_service import _extract_rows
from .downtime_smcs_classification_service import (
    DowntimeSMCSClassificationService,
    serialize_preview_job,
)
from .models import SMCSClassificationJob
from .power_automate import execute_dax_via_flow
from .powerbi import resolve_dataset_roles, resolve_workspace_dataset_id


logger = logging.getLogger(__name__)


def api_login_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse(
                {
                    "ok": False,
                    "error": "Your session has expired. Sign in again and retry.",
                    "error_code": "AUTHENTICATION_REQUIRED",
                },
                status=401,
            )
        return view(request, *args, **kwargs)

    # Authentication is handled here so API callers receive JSON instead of
    # the HTML redirect produced by LoginRequiredMiddleware.
    wrapped.login_required = False
    return wrapped


def _payload(request) -> dict:
    try:
        value = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid JSON payload.") from exc
    if not isinstance(value, dict):
        raise ValueError("The request payload must be an object.")
    return value


def _run(request, session_id, callback):
    try:
        session = get_user_session(request.user, session_id)
        return JsonResponse({"ok": True, **callback(session)})
    except (ValueError, RuntimeError) as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    except Exception as exc:
        return JsonResponse(
            {
                "ok": False,
                "error": "The Power BI query could not be completed.",
                "detail": str(exc),
            },
            status=502,
        )


@api_login_required
@require_POST
def open_api(request):
    try:
        data = _payload(request)
        session, created = open_explorer(
            user=request.user,
            conversation_id=str(data.get("conversation_id") or ""),
            source_question=str(data.get("source_question") or ""),
            current_context=data.get("current_context") or {},
            selected_driver=str(data.get("selected_value") or ""),
            report_id=str(data.get("report_id") or ""),
        )
        return JsonResponse({
            "ok": True,
            **initial_payload(session, created),
        })
    except (ValueError, RuntimeError) as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    except Exception as exc:
        logger.exception(
            "downtime_explorer_open_failed",
            extra={"user_id": request.user.pk},
        )
        return JsonResponse(
            {
                "ok": False,
                "error": "The Downtime Root Cause Explorer could not be opened.",
                "detail": str(exc),
            },
            status=502,
        )


@api_login_required
@require_POST
def availability_diagnostics_api(request):
    try:
        data = _payload(request)
        intent = data.get("intent") if isinstance(data.get("intent"), dict) else {}
        work_type = str(data.get("work_type") or "").strip()
        query = build_availability_diagnostics_dax(
            intent,
            work_type=work_type,
        )
        dataset_name = str(data.get("dataset_name") or "FPR Global DB + RLS")
        site = (intent.get("filters") or {}).get("minesite")
        site_values = site if isinstance(site, list) else ([site] if site else [])
        roles = resolve_dataset_roles(dataset_name, [str(item) for item in site_values])
        result = execute_dax_via_flow({
            "datasetId": resolve_workspace_dataset_id(dataset_name),
            "datasetName": dataset_name,
            "query": query["dax"],
            "question": "Availability downtime diagnostics by Work Type",
            "metric": query["metric"],
            "measure": query["measure"],
            "filters": query["filters"],
            "section": "performance",
            "rlsRole": roles[0] if roles else "",
            "roles": roles,
        })
        diagnostics = parse_availability_diagnostics_rows(_extract_rows(result))
        diagnostics["work_type"] = query["work_type"]
        return JsonResponse({"ok": True, "diagnostics": diagnostics})
    except (ValueError, RuntimeError) as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    except Exception as exc:
        return JsonResponse({
            "ok": False,
            "error": "The downtime diagnostics could not be refreshed.",
            "detail": str(exc),
        }, status=502)


@api_login_required
@require_POST
def summary_api(request, session_id):
    return _run(request, session_id, load_summary)


@api_login_required
@require_POST
def breakdown_api(request, session_id):
    try:
        data = _payload(request)
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    return _run(
        request,
        session_id,
        lambda session: load_breakdown(
            session,
            str(data.get("dimension") or "work_type"),
        ),
    )


@api_login_required
@require_POST
def equipment_api(request, session_id):
    return _run(request, session_id, load_equipment)


@api_login_required
@require_POST
def events_api(request, session_id):
    try:
        data = _payload(request)
        limit = max(1, min(int(data.get("limit") or 300), 500))
    except (ValueError, TypeError) as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    return _run(request, session_id, lambda session: load_events(session, limit=limit))


@api_login_required
@require_POST
def comments_api(request, session_id):
    return _run(request, session_id, load_comments)


@api_login_required
@require_POST
def analyze_comments_api(request, session_id):
    return _run(request, session_id, run_comment_analysis)


@api_login_required
@require_POST
def repeated_failures_api(request, session_id):
    try:
        data = _payload(request)
        window_days = int(data.get("window_days") or 90)
    except (ValueError, TypeError) as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    return _run(
        request,
        session_id,
        lambda session: load_repeated_failures(session, window_days),
    )


@api_login_required
@require_POST
def smcs_breakdown_api(request, session_id):
    return _run(request, session_id, load_smcs_breakdown)


@api_login_required
@require_POST
def smcs_classification_preview_api(request, session_id):
    if not is_platform_admin(request.user):
        return JsonResponse({"ok": False, "error": "Admin access required."}, status=403)
    try:
        session = get_user_session(request.user, session_id)
        job = DowntimeSMCSClassificationService().start_preview(
            user=request.user,
            session=session,
        )
        return JsonResponse({"ok": True, **serialize_preview_job(job)})
    except (ValueError, RuntimeError) as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)


@api_login_required
@require_GET
def smcs_classification_job_api(request, session_id, job_id):
    if not is_platform_admin(request.user):
        return JsonResponse({"ok": False, "error": "Admin access required."}, status=403)
    try:
        get_user_session(request.user, session_id)
        job = SMCSClassificationJob.objects.get(
            pk=job_id,
            explorer_session_id=session_id,
            user=request.user,
        )
        return JsonResponse({"ok": True, **serialize_preview_job(job)})
    except SMCSClassificationJob.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Preview job not found."}, status=404)


@api_login_required
@require_POST
def select_api(request, session_id):
    try:
        data = _payload(request)
        session = get_user_session(request.user, session_id)
        session = select_dimension(
            session,
            dimension_code=str(data.get("dimension") or ""),
            value=str(data.get("value") or ""),
        )
        return JsonResponse({"ok": True, **serialize_session(session)})
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)


@api_login_required
@require_POST
def reset_api(request, session_id):
    return _run(
        request,
        session_id,
        lambda session: serialize_session(reset_explorer(session)),
    )


@api_login_required
@require_POST
def back_api(request, session_id):
    return _run(
        request,
        session_id,
        lambda session: serialize_session(back_explorer(session)),
    )


@api_login_required
@require_POST
def navigate_api(request, session_id):
    return _run(
        request,
        session_id,
        lambda session: {
            "navigation": navigation_payload(session),
            "suggested_actions": suggested_actions(session),
        },
    )
