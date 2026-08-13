from __future__ import annotations

import json
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_http_methods

from .access_control import is_platform_admin
from .active_directory_service import active_directory_integration, search_directory_identities
from .models import PlatformUser
from .user_access_service import (
    UserAccessValidationError,
    access_options,
    add_directory_user,
    authorized_users_queryset,
    serialize_audit,
    serialize_user,
    set_user_status,
    update_user_access,
)


def _positive_int(value, default: int) -> int:
    try:
        return max(1, int(value or default))
    except (TypeError, ValueError):
        return default


def _error(message, *, status=400, field=""):
    payload = {"ok": False, "error": str(message)}
    if field:
        payload["field_errors"] = {field: str(message)}
    return JsonResponse(payload, status=status)


def _admin(request):
    return bool(request.user.is_authenticated and is_platform_admin(request.user))


def _payload(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise UserAccessValidationError("The request body must be valid JSON.")


def _rate_limited(request, bucket: str, *, limit=60, seconds=60):
    identity = request.user.pk or request.META.get("REMOTE_ADDR") or "anonymous"
    window = int(__import__("time").time() // seconds)
    key = f"access-control:{bucket}:{identity}:{window}"
    try:
        count = cache.incr(key)
    except ValueError:
        cache.set(key, 1, seconds + 5)
        count = 1
    return count > limit


@require_http_methods(["GET", "POST"])
def users_api(request):
    if not _admin(request):
        return _error("Administrator access is required.", status=403)
    if request.method == "POST":
        return add_user_api(request)
    page_size = max(10, min(_positive_int(request.GET.get("page_size"), 25), 50))
    paginator = Paginator(authorized_users_queryset(request.GET), page_size)
    page = paginator.get_page(_positive_int(request.GET.get("page"), 1))
    all_users = PlatformUser.objects.all()
    return JsonResponse({
        "ok": True,
        "count": paginator.count,
        "page": page.number,
        "page_size": page_size,
        "pages": paginator.num_pages,
        "summary": {
            "total": all_users.count(),
            "active": all_users.filter(is_active=True).count(),
            "administrators": all_users.filter(is_active=True, is_platform_admin=True).count(),
            "ad_managed": all_users.filter(auth_source="active_directory", directory_roles_managed=True).count(),
        },
        "results": [serialize_user(item) for item in page.object_list],
    })


@require_http_methods(["GET"])
def user_detail_api(request, user_id):
    if not _admin(request):
        return _error("Administrator access is required.", status=403)
    item = get_object_or_404(PlatformUser, pk=user_id)
    return JsonResponse({"ok": True, "user": serialize_user(item, detail=True)})


@require_http_methods(["GET"])
def directory_search_api(request):
    if not _admin(request):
        return _error("Administrator access is required.", status=403)
    if _rate_limited(request, "directory-search"):
        return _error("Too many directory searches. Wait a moment and try again.", status=429)
    query = " ".join(str(request.GET.get("q") or "").split())
    if len(query) < 2:
        return _error("Enter at least two characters.", status=400, field="q")
    integration = active_directory_integration()
    if not integration:
        return _error("Active Directory is not configured.", status=503)
    try:
        identities = search_directory_identities(integration, query, limit=25)
    except Exception:
        return _error("The company directory is temporarily unavailable.", status=503)
    object_ids = [identity.object_id for identity in identities]
    upns = [identity.upn for identity in identities]
    authorized = PlatformUser.objects.filter(
        Q(directory_object_id__in=object_ids) | Q(user_principal_name__in=upns)
    )
    by_object = {item.directory_object_id: item for item in authorized if item.directory_object_id}
    by_upn = {item.user_principal_name.casefold(): item for item in authorized}
    domain = str((integration.settings_json or {}).get("netbios_domain") or "").upper()
    results = []
    for identity in identities:
        existing = by_object.get(identity.object_id) or by_upn.get(identity.upn.casefold())
        results.append({
            "directory_object_id": identity.object_id,
            "directory_username": identity.username,
            "display_name": identity.display_name,
            "upn": identity.upn,
            "email": identity.email or identity.upn,
            "account_name": f"{domain}\\{identity.username}" if domain else identity.username,
            "company": domain,
            "department": "",
            "already_authorized": bool(existing),
            "mining360_user_id": existing.pk if existing else None,
        })
    return JsonResponse({"ok": True, "query": query, "count": len(results), "next": None, "results": results})


@require_http_methods(["GET"])
def options_api(request):
    if not _admin(request):
        return _error("Administrator access is required.", status=403)
    return JsonResponse({"ok": True, **access_options(request.user)})


@require_http_methods(["POST"])
def add_user_api(request):
    if not _admin(request):
        return _error("Administrator access is required.", status=403)
    try:
        item = add_directory_user(_payload(request), request.user)
        return JsonResponse({"ok": True, "user": serialize_user(item, detail=True)}, status=201)
    except UserAccessValidationError as exc:
        return _error(exc, status=409 if "already authorized" in str(exc).lower() else 400, field=exc.field)
    except Exception:
        return _error("The user could not be added. Verify the directory account and access settings.", status=503)


@require_http_methods(["PATCH"])
def update_access_api(request, user_id):
    if not _admin(request):
        return _error("Administrator access is required.", status=403)
    item = get_object_or_404(PlatformUser, pk=user_id)
    try:
        item = update_user_access(item, _payload(request), request.user)
        return JsonResponse({"ok": True, "user": serialize_user(item, detail=True)})
    except UserAccessValidationError as exc:
        return _error(exc, field=exc.field)


@require_http_methods(["POST"])
def status_api(request, user_id):
    if not _admin(request):
        return _error("Administrator access is required.", status=403)
    item = get_object_or_404(PlatformUser, pk=user_id)
    try:
        item = set_user_status(item, bool(_payload(request).get("active")), request.user)
        return JsonResponse({"ok": True, "user": serialize_user(item, detail=True)})
    except UserAccessValidationError as exc:
        return _error(exc, field=exc.field)


@require_http_methods(["GET"])
def audit_api(request, user_id):
    if not _admin(request):
        return _error("Administrator access is required.", status=403)
    item = get_object_or_404(PlatformUser, pk=user_id)
    logs = item.access_audit_logs.select_related("actor")[:50]
    return JsonResponse({"ok": True, "results": [serialize_audit(log) for log in logs]})
