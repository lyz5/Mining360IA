from __future__ import annotations


class Mining360ContentSecurityPolicyMiddleware:
    """Restrict report and Power Apps frames without weakening other browser protections."""

    FRAME_POLICY = (
        "frame-src 'self' https://app.powerbi.com https://*.powerbi.com "
        "https://apps.powerapps.com https://*.powerapps.com https://login.microsoftonline.com; "
        "frame-ancestors 'self'"
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if "Content-Security-Policy" not in response:
            response["Content-Security-Policy"] = self.FRAME_POLICY
        return response
