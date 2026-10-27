from __future__ import annotations

import re
from django.http import JsonResponse
from django.shortcuts import redirect
from .platform_roles import active_profile, explicit_roles, has_business_role, is_super_admin, can_manage_users

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

MODULES = {
    "excellence_center": "Excellence Center",
    "business_overview": "Business Overview",
    "resources": "Ressources",
    "reporting": "Reporting",
    "chatbot": "M360 Chatbot",
    "ai": "IA",
    "data": "Data",
    "sources": "Data Source",
}

MODULE_PATH_PREFIXES = (
    ("excellence_center", ("/excellence-center/", "/api/home/")),
    ("business_overview", ("/business-review/", "/api/business-review/")),
    ("resources", ("/resources/",)),
    ("reporting", ("/business-performance/",)),
    ("reporting", ("/reporting/", "/reports/", "/api/reporting/", "/powerbi-interaction/")),
    ("chatbot", ("/codex-chatbot/", "/ai/", "/api/ai/")),
    ("data", ("/data/", "/data-browsers", "/data-quality/")),
    ("sources", ("/data-sources/",)),
)

ADMIN_ONLY_PREFIXES = (
    "/config/downtime-checking/",
    "/config/deployment/",
    "/api/deployment/",
    "/users/",
    "/api/access-control/",
    "/ia-config/",
    "/ia-config/agents/",
    "/knowledge-base/",
    "/system-config/",
    "/business-performance/config/",
)

ADMIN_WRITE_PREFIXES = (
    "/config/downtime-checking/",
    "/config/deployment/",
    "/api/deployment/",
    "/data-browsers",
    "/data-sources/",
    "/ia-config/",
    "/knowledge-base/",
    "/system-config/",
    "/users/",
    "/api/access-control/",
    "/resources/upload/",
)

WRITE_EXEMPT_PREFIXES = (
    "/ai/ask/",
    "/ai/semantic-test/",
    "/data-quality/run/",
)


def wants_json(request) -> bool:
    return (
        request.path_info.startswith("/api/")
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in request.headers.get("Accept", "")
        or request.path_info.rstrip("/").endswith("/api")
    )


def is_platform_admin(user) -> bool:
    # Existing callers guard sensitive configuration and RLS bypasses.
    return is_super_admin(user)


def user_module_access(user) -> dict[str, bool]:
    if is_platform_admin(user):
        return {code: True for code in MODULES}
    platform_user = active_profile(user)
    if not platform_user or not platform_user.is_active:
        return {code: False for code in MODULES}
    return {
        "excellence_center": has_business_role(user, "excellence_center"),
        "business_overview": has_business_role(user, "business_overview"),
        "resources": has_business_role(user, "resources"),
        "reporting": has_business_role(user, "reporting"),
        # `ai` remains an internal compatibility capability. User-facing
        # chatbot access is governed by the explicit Chatbot role.
        "ai": platform_user.can_access_ai,
        "chatbot": has_business_role(user, "chatbot"),
        "data": platform_user.can_access_data,
        "sources": platform_user.can_access_sources,
    }


def has_module_access(user, module_code: str) -> bool:
    return bool(user_module_access(user).get(module_code))


def module_for_path(path: str) -> str | None:
    for module_code, prefixes in MODULE_PATH_PREFIXES:
        if path.startswith(prefixes):
            return module_code
    return None


def forbidden_response(request, message: str = "Access denied."):
    if wants_json(request):
        return JsonResponse({"ok": False, "error": message}, status=403)
    return redirect("dashboard")


def enforce_request_access(request):
    path = request.path_info
    if request.method not in SAFE_METHODS and path.startswith("/users/") and path.rstrip("/") != "/users":
        return JsonResponse({"ok": False, "error": "Use the Users access panel to manage roles."}, status=403)
    if is_platform_admin(request.user):
        return None

    if path.startswith(("/api/access-control/", "/users/")):
        if not can_manage_users(request.user):
            return forbidden_response(request, "Admin access required.")
        # Old form endpoints do not implement the new privilege checks.
        if path.startswith("/users/") and path.rstrip("/") != "/users":
            return forbidden_response(request, "Use the Users access panel.")
        return None

    if path.startswith(ADMIN_ONLY_PREFIXES):
        return forbidden_response(request, "Admin access required.")

    module_code = module_for_path(path)
    # Chatbot has its own decorator, which also supports the controlled pilot
    # allowlist. Let that policy evaluate the request instead of blocking
    # pilot users at the generic module gate.
    if module_code == "chatbot" and path.startswith("/codex-chatbot/"):
        return None
    from .site_access_service import site_role_enabled
    if site_role_enabled(request.user) and module_code == "reporting":
        report_id = r"[0-9a-fA-F-]{36}"
        site_reporting_paths = (
            path == "/reporting/"
            or path == "/api/reporting/hub/"
            or bool(re.fullmatch(rf"/reporting/reports/{report_id}/(?:launch/|refresh/|troubleshoot/)?", path))
            or bool(re.fullmatch(rf"/reports/{report_id}/", path))
            or bool(re.fullmatch(rf"/api/reporting/reports/{report_id}/(?:favorite|refresh|troubleshoot|viewer-configuration|viewer-switcher)/", path))
            or bool(re.fullmatch(rf"/powerbi-interaction/(?:embed-config|preflight)/{report_id}/", path))
        )
        if not site_reporting_paths:
            return forbidden_response(request, "The Site role can open only reports assigned with MineSite RLS.")
    # Legacy Business Overview permissions and library access remain intact.
    legacy_new_route = module_code in {"business_overview", "resources", "excellence_center"} and explicit_roles(active_profile(request.user)) is None
    if module_code and not legacy_new_route and not has_module_access(request.user, module_code):
        return forbidden_response(request, f"{MODULES[module_code]} role required.")

    if request.method not in SAFE_METHODS:
        if path.startswith(WRITE_EXEMPT_PREFIXES):
            return None
        if path.startswith(ADMIN_WRITE_PREFIXES):
            return forbidden_response(request, "Only administrators can create, modify or delete records.")
    return None
