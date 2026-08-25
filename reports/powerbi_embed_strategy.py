from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from .access_control import is_platform_admin
from .microsoft_delegated_auth import (
    EntraAuthenticationError,
    InteractiveAuthenticationRequired,
    acquire_powerbi_token_silent,
    delegated_account_summary,
)
from .models import PlatformUser, PowerBIAuthenticationAuditLog, PowerBIReport
from .powerbi import PowerBIReport as RuntimePowerBIReport, generate_report_embed_token


POWERBI_API_ROOT = "https://api.powerbi.com/v1.0/myorg"
HTTP = requests.Session()
HTTP.trust_env = False


class PowerBIEmbedError(RuntimeError):
    def __init__(self, message: str, *, code: str = "powerbi_embed_failed", status: int = 503):
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class PowerBIEmbedStrategy:
    strategy: str
    token_type: str
    requires_interactive_user: bool
    reason: str


def feature_enabled(setting_name: str, user) -> bool:
    mode = str(getattr(settings, setting_name, "Disabled") or "Disabled").strip().casefold()
    if mode in {"production", "enabled", "true", "1", "on"}:
        return True
    if mode in {"admin only", "admin_only", "pilot"}:
        return is_platform_admin(user)
    return False


class PowerBIEmbedStrategyResolver:
    @staticmethod
    def resolve(report: PowerBIReport, user) -> PowerBIEmbedStrategy:
        if report.requires_user_identity or report.authentication_mode == "user_owns_data":
            if not feature_enabled("ENABLE_USER_OWNS_DATA_EMBEDDING", user):
                raise PowerBIEmbedError(
                    "Interactive corporate authentication is not enabled for this user.",
                    code="user_owned_embedding_disabled",
                    status=403,
                )
            return PowerBIEmbedStrategy(
                strategy="user_owns_data",
                token_type="Aad",
                requires_interactive_user=True,
                reason="The report requires the connected corporate Microsoft identity.",
            )
        return PowerBIEmbedStrategy(
            strategy="app_owns_data",
            token_type="Embed",
            requires_interactive_user=False,
            reason="The report uses the Mining 360 service principal.",
        )


def _audit(request, report, event_type, *, status="success", code="", message="", metadata=None):
    try:
        PowerBIAuthenticationAuditLog.objects.create(
            user=request.user if request.user.is_authenticated else None,
            report=report,
            event_type=event_type,
            status=status,
            error_code=code,
            message=str(message or "")[:2000],
            metadata_json=metadata or {},
        )
    except Exception:
        pass


def corporate_connect_url(request, report: PowerBIReport) -> str:
    return f"{reverse('powerbi-auth-start')}?{urlencode({'report_id': report.report_id, 'next': request.get_full_path()})}"


def _validate_user_identity(request, report: PowerBIReport, token) -> PlatformUser:
    try:
        platform_user = request.user.platformuser
    except PlatformUser.DoesNotExist as exc:
        raise PowerBIEmbedError(
            "Your Mining 360 account is not linked to a corporate identity.",
            code="identity_mapping_missing",
            status=403,
        ) from exc
    required_tenant = (report.required_entra_tenant_id or "").strip().casefold()
    if required_tenant and token.tenant_id.casefold() != required_tenant:
        raise PowerBIEmbedError(
            "Your Microsoft account belongs to a different tenant from the Prime Movers application.",
            code="wrong_tenant",
            status=403,
        )
    if platform_user.entra_tenant_id and token.tenant_id and platform_user.entra_tenant_id != token.tenant_id:
        raise PowerBIEmbedError(
            "The connected Microsoft tenant does not match your Mining 360 identity.",
            code="identity_tenant_mismatch",
            status=403,
        )
    if platform_user.azure_ad_id and token.object_id and platform_user.azure_ad_id != token.object_id:
        raise PowerBIEmbedError(
            "The connected Microsoft account does not match your Mining 360 identity.",
            code="identity_object_mismatch",
            status=403,
        )
    platform_user.entra_tenant_id = token.tenant_id or platform_user.entra_tenant_id
    platform_user.last_entra_authenticated_at = timezone.now()
    platform_user.save(update_fields=["entra_tenant_id", "last_entra_authenticated_at", "updated_at"])
    return platform_user


def _verify_delegated_report_access(report: PowerBIReport, access_token: str) -> str:
    response = HTTP.get(
        f"{POWERBI_API_ROOT}/groups/{report.workspace_id}/reports/{report.report_id}",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    if response.status_code in {401, 403, 404}:
        raise PowerBIEmbedError(
            "You are signed in, but you do not have access to the Prime Movers Operational Status report. "
            "Contact the Power BI administrator.",
            code="powerbi_report_access_denied",
            status=403,
        )
    if response.status_code != 200:
        raise PowerBIEmbedError(
            "Power BI could not validate your access to this report.",
            code="powerbi_preflight_failed",
            status=503,
        )
    return str(response.json().get("embedUrl") or report.embed_url)


def build_embed_configuration(request, report: PowerBIReport, *, role: str = "Global") -> dict:
    strategy = PowerBIEmbedStrategyResolver.resolve(report, request.user)
    if not report.embed_url:
        raise PowerBIEmbedError("The report embed URL is not configured.", code="embed_url_missing", status=400)
    runtime_report = RuntimePowerBIReport(
        id=report.report_id,
        name=report.report_name,
        display_name=report.display_name,
        dataset_id=report.semantic_model_id,
        web_url="",
        embed_url=report.embed_url,
        report_type="PowerBIReport",
    )
    opening_profile = {
        "name": report.opening_profile_name or "Standard Power BI",
        "displayOption": report.display_option,
        "backgroundType": report.background_type,
    }
    settings = {
        "panes": {
            "filters": {"visible": report.filter_pane_visible},
            "pageNavigation": {"visible": report.page_navigation_visible},
            "bookmarks": {"visible": report.bookmarks_pane_visible},
        },
    }
    if strategy.strategy == "app_owns_data":
        token = generate_report_embed_token(runtime_report, [role])
        config = {
            "type": "report",
            "id": runtime_report.id,
            "embedUrl": runtime_report.embed_url,
            "accessToken": token,
            "tokenType": "Embed",
            "authenticationMode": "app_owns_data",
            "requiresInteractiveUser": False,
            "settings": settings,
            "openingProfile": opening_profile,
        }
        if report.default_page_internal_name:
            config["pageName"] = report.default_page_internal_name
        return config

    _audit(request, report, "embed_requested", metadata={"authentication_mode": strategy.strategy})
    try:
        delegated = acquire_powerbi_token_silent(request)
        platform_user = _validate_user_identity(request, report, delegated)
        embed_url = _verify_delegated_report_access(report, delegated.access_token)
    except InteractiveAuthenticationRequired:
        _audit(request, report, "embed_denied", status="authentication_required", code="interaction_required")
        raise
    except (EntraAuthenticationError, PowerBIEmbedError) as exc:
        _audit(
            request,
            report,
            "embed_denied",
            status="failed",
            code=getattr(exc, "code", "authentication_failed"),
            message=str(exc),
        )
        raise
    config = {
        "type": "report",
        "id": runtime_report.id,
        "embedUrl": embed_url or runtime_report.embed_url,
        "accessToken": delegated.access_token,
        "tokenType": "Aad",
        "authenticationMode": "user_owns_data",
        "requiresInteractiveUser": True,
        "expiresAt": delegated.expires_at,
        "user": {
            "upn": platform_user.user_principal_name,
            "displayName": platform_user.display_name,
        },
        "settings": settings,
        "openingProfile": opening_profile,
    }
    if report.default_page_internal_name:
        config["pageName"] = report.default_page_internal_name
    return config


class PrimeMoversAccessPreflightService:
    @staticmethod
    def run(request, report: PowerBIReport) -> dict:
        strategy = PowerBIEmbedStrategyResolver.resolve(report, request.user)
        account = delegated_account_summary(request)
        result = {
            "authentication_mode": strategy.strategy,
            "entra_authenticated": False,
            "correct_tenant": None,
            "powerbi_token_available": False,
            "powerbi_report_access": False,
            "powerapps_access": "not_verifiable_from_mining360",
            "ready_to_embed": False,
            "warnings": ["Power Apps access will be validated when the visual loads."],
            "user": {"upn": account.get("username") or ""},
        }
        if strategy.strategy != "user_owns_data":
            return result
        try:
            token = acquire_powerbi_token_silent(request)
            _validate_user_identity(request, report, token)
            _verify_delegated_report_access(report, token.access_token)
            result.update({
                "entra_authenticated": True,
                "correct_tenant": True,
                "powerbi_token_available": True,
                "powerbi_report_access": True,
                "ready_to_embed": True,
            })
        except InteractiveAuthenticationRequired:
            result["connect_url"] = corporate_connect_url(request, report)
        except (EntraAuthenticationError, PowerBIEmbedError) as exc:
            result["error"] = str(exc)
            result["error_code"] = getattr(exc, "code", "preflight_failed")
        return result
