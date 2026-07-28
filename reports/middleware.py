from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse

from .access_control import enforce_request_access


class PlatformLoginRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path_info
        exempt_prefixes = (
            reverse("login"),
            reverse("auth-start"),
            reverse("auth-callback"),
            reverse("logout"),
            "/admin/",
            settings.STATIC_URL,
        )
        if path.startswith(exempt_prefixes):
            return self.get_response(request)
        if not request.user.is_authenticated:
            if (
                path.startswith("/ai/downtime-explorer/")
                or "application/json" in request.headers.get("Accept", "")
            ):
                return JsonResponse(
                    {
                        "ok": False,
                        "error": "Your session has expired. Sign in again and retry.",
                        "error_code": "AUTHENTICATION_REQUIRED",
                    },
                    status=401,
                )
            login_url = f"{reverse('login')}?next={request.get_full_path()}"
            return redirect(login_url)
        access_response = enforce_request_access(request)
        if access_response is not None:
            return access_response
        return self.get_response(request)
