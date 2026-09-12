from __future__ import annotations

import json

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from .fleet_excel_export_service import FleetExcelExportService
from .fleet_performance_excel_export_service import FleetPerformanceExcelExportService


def _body(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError("Invalid JSON payload.") from exc


@login_required
@require_http_methods(["POST"])
def fleet_export_api(request):
    try:
        payload = _body(request)
        export = FleetExcelExportService(request.user).build(payload.get("artifact_id"))
        artifact = export["artifact"]
        return JsonResponse({
            "export_id": str(artifact.id),
            "file_name": export["file_name"],
            "row_count": export["row_count"],
            "status": "ready",
            "download_url": reverse("fleet-export-download", args=[artifact.id]),
            "expires_at": None,
        })
    except PermissionDenied as exc:
        return JsonResponse({"error": str(exc)}, status=403)
    except ValidationError as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@login_required
@require_http_methods(["GET"])
def fleet_export_download(request, export_id):
    try:
        export = FleetExcelExportService(request.user).build(export_id)
        response = FileResponse(
            export["content"],
            as_attachment=True,
            filename=export["file_name"],
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response
    except PermissionDenied as exc:
        return JsonResponse({"error": str(exc)}, status=403)
    except ValidationError as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@login_required
@require_http_methods(["POST"])
def fleet_performance_export_api(request):
    try:
        payload = _body(request)
        export = FleetPerformanceExcelExportService(request.user).build(payload.get("artifact_id"))
        artifact = export["artifact"]
        return JsonResponse({
            "export_id": str(artifact.id),
            "file_name": export["file_name"],
            "row_count": export["row_count"],
            "status": "ready",
            "download_url": reverse("fleet-performance-export-download", args=[artifact.id]),
            "expires_at": None,
        })
    except PermissionDenied as exc:
        return JsonResponse({"error": str(exc)}, status=403)
    except ValidationError as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@login_required
@require_http_methods(["GET"])
def fleet_performance_export_download(request, export_id):
    try:
        export = FleetPerformanceExcelExportService(request.user).build(export_id)
        response = FileResponse(
            export["content"],
            as_attachment=True,
            filename=export["file_name"],
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response
    except PermissionDenied as exc:
        return JsonResponse({"error": str(exc)}, status=403)
    except ValidationError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
