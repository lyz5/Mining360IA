from __future__ import annotations

import json
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import msal
from django.conf import settings
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from .ad_auth import ad_config
from .system_configuration_service import _fernet, integration_value


POWERBI_DELEGATED_SCOPES = [
    "https://analysis.windows.net/powerbi/api/Report.Read.All",
]
TOKEN_CACHE_SESSION_KEY = "microsoft_delegated_token_cache"
AUTH_FLOW_SESSION_KEY = "microsoft_delegated_auth_flow"
ACCOUNT_SESSION_KEY = "microsoft_delegated_account"


class EntraAuthenticationError(RuntimeError):
    def __init__(self, message: str, *, code: str = "entra_authentication_failed"):
        super().__init__(message)
        self.code = code


class EntraConfigurationError(EntraAuthenticationError):
    pass


class InteractiveAuthenticationRequired(EntraAuthenticationError):
    def __init__(self, message: str = "Corporate Microsoft authentication is required."):
        super().__init__(message, code="interaction_required")


@dataclass(frozen=True)
class DelegatedToken:
    access_token: str
    expires_at: int
    tenant_id: str
    object_id: str
    username: str
    display_name: str


def _configured_redirect_uri(request) -> str:
    configured = (
        integration_value("Authentication", "redirect_uri", "")
        or getattr(settings, "AZURE_AD_REDIRECT_URI", "")
    )
    redirect_uri = configured.strip() or request.build_absolute_uri(reverse("auth-callback"))
    parsed = urlparse(redirect_uri)
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise EntraConfigurationError(
            "Microsoft Entra requires an HTTPS callback for non-localhost web applications. "
            f"Register and configure: https://{request.get_host()}{reverse('auth-callback')}",
            code="https_callback_required",
        )
    return redirect_uri


def _load_cache(request) -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    encrypted = request.session.get(TOKEN_CACHE_SESSION_KEY)
    if not encrypted:
        return cache
    try:
        payload = _fernet().decrypt(encrypted.encode("ascii")).decode("utf-8")
        cache.deserialize(payload)
    except Exception:
        request.session.pop(TOKEN_CACHE_SESSION_KEY, None)
    return cache


def _save_cache(request, cache: msal.SerializableTokenCache) -> None:
    if cache.has_state_changed:
        serialized = cache.serialize().encode("utf-8")
        request.session[TOKEN_CACHE_SESSION_KEY] = _fernet().encrypt(serialized).decode("ascii")
        request.session.modified = True


def _application(request):
    config = ad_config()
    if not config.get("tenant_id") or not config.get("client_id") or not config.get("client_secret"):
        raise EntraConfigurationError(
            "The Microsoft Entra interactive application is not fully configured.",
            code="entra_application_not_configured",
        )
    cache = _load_cache(request)
    app = msal.ConfidentialClientApplication(
        config["client_id"],
        authority=f"https://login.microsoftonline.com/{config['tenant_id']}",
        client_credential=config["client_secret"],
        token_cache=cache,
    )
    return app, cache, config


def begin_powerbi_authorization(request, *, return_to: str, report_id: str = "") -> str:
    app, cache, _ = _application(request)
    redirect_uri = _configured_redirect_uri(request)
    safe_return = return_to if url_has_allowed_host_and_scheme(
        return_to,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ) else reverse("reporting")
    flow = app.initiate_auth_code_flow(
        scopes=POWERBI_DELEGATED_SCOPES,
        redirect_uri=redirect_uri,
        prompt="select_account",
    )
    if "auth_uri" not in flow:
        raise EntraAuthenticationError(
            flow.get("error_description") or "Microsoft Entra authorization could not be started.",
            code=flow.get("error") or "authorization_start_failed",
        )
    flow["mining360_purpose"] = "powerbi"
    flow["mining360_return_to"] = safe_return
    flow["mining360_report_id"] = report_id
    request.session[AUTH_FLOW_SESSION_KEY] = flow
    _save_cache(request, cache)
    return flow["auth_uri"]


def has_pending_powerbi_flow(request) -> bool:
    flow = request.session.get(AUTH_FLOW_SESSION_KEY) or {}
    return bool(flow.get("mining360_purpose") == "powerbi")


def complete_powerbi_authorization(request) -> tuple[dict, str, str]:
    flow = request.session.pop(AUTH_FLOW_SESSION_KEY, None)
    if not flow or flow.get("mining360_purpose") != "powerbi":
        raise EntraAuthenticationError("The Microsoft authentication session has expired.", code="flow_expired")
    app, cache, _ = _application(request)
    try:
        result = app.acquire_token_by_auth_code_flow(flow, dict(request.GET))
    except ValueError as exc:
        raise EntraAuthenticationError("Invalid Microsoft authentication state.", code="invalid_state") from exc
    _save_cache(request, cache)
    if "access_token" not in result:
        raise EntraAuthenticationError(
            result.get("error_description") or "Microsoft authentication failed.",
            code=result.get("error") or "token_exchange_failed",
        )
    claims = result.get("id_token_claims") or {}
    username = claims.get("preferred_username") or claims.get("upn") or ""
    cached_accounts = app.get_accounts(username=username or None)
    cached_account = cached_accounts[0] if cached_accounts else {}
    account = {
        "home_account_id": cached_account.get("home_account_id") or "",
        "tenant_id": claims.get("tid") or "",
        "object_id": claims.get("oid") or "",
        "username": username,
        "display_name": claims.get("name") or "",
    }
    request.session[ACCOUNT_SESSION_KEY] = account
    return account, flow.get("mining360_return_to") or reverse("reporting"), flow.get("mining360_report_id") or ""


def _select_account(app, request):
    expected = request.session.get(ACCOUNT_SESSION_KEY) or {}
    accounts = app.get_accounts(username=expected.get("username") or None)
    if not accounts:
        accounts = app.get_accounts()
    if not accounts:
        return None
    expected_home_id = expected.get("home_account_id")
    if expected_home_id:
        for account in accounts:
            if account.get("home_account_id") == expected_home_id:
                return account
    return accounts[0]


def acquire_powerbi_token_silent(request) -> DelegatedToken:
    app, cache, _ = _application(request)
    account = _select_account(app, request)
    if not account:
        raise InteractiveAuthenticationRequired()
    result = app.acquire_token_silent(POWERBI_DELEGATED_SCOPES, account=account)
    _save_cache(request, cache)
    if not result or "access_token" not in result:
        raise InteractiveAuthenticationRequired()
    claims = result.get("id_token_claims") or {}
    session_account = request.session.get(ACCOUNT_SESSION_KEY) or {}
    expires_at = int(result.get("expires_on") or (time.time() + int(result.get("expires_in") or 3600)))
    return DelegatedToken(
        access_token=result["access_token"],
        expires_at=expires_at,
        tenant_id=str(claims.get("tid") or session_account.get("tenant_id") or ""),
        object_id=str(claims.get("oid") or session_account.get("object_id") or ""),
        username=str(account.get("username") or session_account.get("username") or ""),
        display_name=str(session_account.get("display_name") or account.get("name") or ""),
    )


def clear_delegated_token_cache(request) -> None:
    request.session.pop(TOKEN_CACHE_SESSION_KEY, None)
    request.session.pop(AUTH_FLOW_SESSION_KEY, None)
    request.session.pop(ACCOUNT_SESSION_KEY, None)
    request.session.modified = True


def delegated_account_summary(request) -> dict:
    value = request.session.get(ACCOUNT_SESSION_KEY) or {}
    return {
        "tenant_id": value.get("tenant_id") or "",
        "object_id": value.get("object_id") or "",
        "username": value.get("username") or "",
        "display_name": value.get("display_name") or "",
    }
