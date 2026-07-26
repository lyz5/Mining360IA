from __future__ import annotations

from django.http import JsonResponse
from django.shortcuts import redirect

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

MODULES = {
    "reporting": "Reporting",
    "ai": "IA",
    "data": "Data",
    "sources": "Data Source",
}

MODULE_PATH_PREFIXES = (
    ("reporting", ("/business-performance/",)),
    ("reporting", ("/reporting/", "/reports/")),
    ("ai", ("/ai/", "/api/ai/")),
    ("data", ("/data/", "/data-browsers", "/data-quality/")),
    ("sources", ("/data-sources/",)),
)

ADMIN_ONLY_PREFIXES = (
    "/users/",
    "/ia-config/",
    "/knowledge-base/",
    "/system-config/",
    "/config/openai-usage/",
    "/api/admin/openai-usage/",
    "/business-performance/config/",
)

ADMIN_WRITE_PREFIXES = (
    "/data-browsers",
    "/data-sources/",
    "/ia-config/",
    "/knowledge-base/",
    "/system-config/",
    "/config/openai-usage/",
    "/api/admin/openai-usage/",
    "/users/",
    "/resources/upload/",
)

WRITE_EXEMPT_PREFIXES = (
    "/ai/ask/",
    "/ai/semantic-test/",
    "/data-quality/run/",
)


def wants_json(request) -> bool:
    return (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in request.headers.get("Accept", "")
        or request.path_info.rstrip("/").endswith("/api")
    )


def is_platform_admin(user) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    platform_user = getattr(user, "platformuser", None)
    return bool(platform_user and platform_user.is_active and platform_user.is_platform_admin)


def user_module_access(user) -> dict[str, bool]:
    if is_platform_admin(user):
        return {code: True for code in MODULES}
    platform_user = getattr(user, "platformuser", None)
    if not platform_user or not platform_user.is_active:
        return {code: False for code in MODULES}
    return {
        "reporting": platform_user.can_access_reporting,
        "ai": platform_user.can_access_ai,
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
    if is_platform_admin(request.user):
        return None

    if path.startswith(ADMIN_ONLY_PREFIXES):
        return forbidden_response(request, "Admin access required.")

    module_code = module_for_path(path)
    if module_code and not has_module_access(request.user, module_code):
        return forbidden_response(request, f"{MODULES[module_code]} role required.")

    if request.method not in SAFE_METHODS:
        if path.startswith(WRITE_EXEMPT_PREFIXES):
            return None
        if path.startswith(ADMIN_WRITE_PREFIXES):
            return forbidden_response(request, "Only administrators can create, modify or delete records.")
    return None
