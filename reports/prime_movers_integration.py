from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from .models import (
    PlatformUser,
    PowerAppsLaunchContext,
    PowerBIReport,
    PrimeMoversIntegrationConfiguration,
    PrimeMoversIntegrationExecutionLog,
    UserExternalIdentity,
)
from .powerbi_embed_strategy import feature_enabled


class PrimeMoversIntegrationError(RuntimeError):
    def __init__(self, message: str, *, code: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class CorporateIdentity:
    windows_identity: str
    normalized_upn: str
    tenant_id: str
    object_id: str
    mapping_status: str
    display_name: str


class CorporateIdentityMappingService:
    @staticmethod
    def resolve(user) -> CorporateIdentity:
        platform_user = PlatformUser.objects.filter(django_user=user).first()
        if not platform_user:
            raise PrimeMoversIntegrationError(
                "Your Mining 360 account is not linked to a corporate directory identity.",
                code="WINDOWS_IDENTITY_NOT_MAPPED",
                status=403,
            )
        external = (
            UserExternalIdentity.objects.filter(
                user=user,
                provider="microsoft_entra",
                active=True,
                mapping_status="validated",
            )
            .order_by("-last_verified_at")
            .first()
        )
        windows_identity = platform_user.directory_username or ""
        if windows_identity and "\\" not in windows_identity:
            domain = str(getattr(settings, "ACTIVE_DIRECTORY_NETBIOS_DOMAIN", "") or "").strip()
            windows_identity = f"{domain}\\{windows_identity}" if domain else windows_identity
        return CorporateIdentity(
            windows_identity=external.windows_identity if external and external.windows_identity else windows_identity,
            normalized_upn=(external.upn if external else platform_user.user_principal_name).casefold(),
            tenant_id=external.tenant_id if external else "",
            object_id=external.external_object_id if external else "",
            mapping_status=external.mapping_status if external else "pending",
            display_name=external.display_name if external and external.display_name else platform_user.display_name,
        )

    @staticmethod
    @transaction.atomic
    def validate_from_microsoft_account(user, account: dict) -> UserExternalIdentity:
        platform_user = PlatformUser.objects.select_for_update().get(django_user=user)
        tenant_id = str(account.get("tenant_id") or "").strip()
        object_id = str(account.get("object_id") or "").strip()
        upn = str(account.get("username") or "").strip().casefold()
        if not tenant_id or not object_id or not upn:
            raise PrimeMoversIntegrationError(
                "Microsoft did not return a complete corporate identity.",
                code="ENTRA_IDENTITY_INCOMPLETE",
            )
        if platform_user.user_principal_name.casefold() != upn:
            raise PrimeMoversIntegrationError(
                "The connected Microsoft account does not match your Mining 360 account.",
                code="ENTRA_UPN_MISMATCH",
                status=403,
            )
        existing = UserExternalIdentity.objects.select_for_update().filter(
            provider="microsoft_entra",
            tenant_id=tenant_id,
            external_object_id=object_id,
        ).first()
        if existing and existing.user_id != user.id:
            raise PrimeMoversIntegrationError(
                "This Microsoft identity is already linked to another Mining 360 user.",
                code="ENTRA_IDENTITY_CONFLICT",
                status=403,
            )
        identity, _ = UserExternalIdentity.objects.update_or_create(
            provider="microsoft_entra",
            tenant_id=tenant_id,
            external_object_id=object_id,
            defaults={
                "user": user,
                "upn": upn,
                "windows_identity": platform_user.directory_username,
                "display_name": platform_user.display_name,
                "mapping_status": "validated",
                "last_verified_at": timezone.now(),
                "active": True,
            },
        )
        platform_user.entra_tenant_id = tenant_id
        platform_user.last_entra_authenticated_at = timezone.now()
        platform_user.save(update_fields=["entra_tenant_id", "last_entra_authenticated_at", "updated_at"])
        return identity


class PrimeMoversContextService:
    ALLOWED_FIELDS = {
        "equipment_id",
        "serial_number",
        "minesite",
        "customer",
        "model",
        "selected_status",
        "page_name",
        "filters",
    }

    @classmethod
    def create_launch_context(cls, *, request, report: PowerBIReport, payload: dict) -> tuple[PowerAppsLaunchContext, str]:
        if not (
            feature_enabled("ENABLE_PRIME_MOVERS_INTEGRATION_RECOVERY", request.user)
            and feature_enabled("ENABLE_PRIME_MOVERS_DUAL_WORKSPACE", request.user)
        ):
            raise PrimeMoversIntegrationError(
                "Prime Movers integration is not enabled for this user.",
                code="PRIME_MOVERS_DISABLED",
                status=403,
            )
        try:
            configuration = report.prime_movers_configuration
        except PrimeMoversIntegrationConfiguration.DoesNotExist as exc:
            raise PrimeMoversIntegrationError(
                "Prime Movers integration has not been configured.",
                code="POWERAPPS_CONFIGURATION_MISSING",
                status=503,
            ) from exc
        if not configuration.active or configuration.validation_status == "Disabled":
            raise PrimeMoversIntegrationError(
                "Prime Movers integration is disabled.",
                code="POWERAPPS_CONFIGURATION_DISABLED",
                status=503,
            )
        if not configuration.powerapps_launch_url:
            raise PrimeMoversIntegrationError(
                "The official Power Apps launch URL has not been configured.",
                code="POWERAPPS_LAUNCH_URL_MISSING",
                status=503,
            )
        identity = CorporateIdentityMappingService.resolve(request.user)
        equipment_id = str(payload.get("equipment_id") or "").strip()
        serial_number = str(payload.get("serial_number") or "").strip()
        preload = payload.get("preload") is True
        if not equipment_id and not serial_number and not preload:
            raise PrimeMoversIntegrationError(
                "Select one machine before opening the operational status form.",
                code="EQUIPMENT_CONTEXT_REQUIRED",
            )
        external = UserExternalIdentity.objects.filter(
            user=request.user,
            provider="microsoft_entra",
            active=True,
            mapping_status="validated",
        ).first()
        # The direct Canvas App authenticates the actual Microsoft user in the
        # browser. A pending Mining 360 identity mapping must not be treated as
        # Power Apps authentication proof, but it also must not block launch.
        expires_at = timezone.now() + timedelta(minutes=configuration.context_expiration_minutes)
        context_id = str(payload.get("context_id") or "").strip()
        context = None
        if context_id:
            try:
                context = PowerAppsLaunchContext.objects.select_for_update().filter(
                    opaque_id=context_id,
                    user=request.user,
                    configuration=configuration,
                    status="active",
                    expires_at__gt=timezone.now(),
                ).first()
            except (ValidationError, ValueError):
                context = None
            if not context:
                raise PrimeMoversIntegrationError(
                    "The Power Apps session has expired. Reload Prime Movers to continue.",
                    code="POWERAPPS_CONTEXT_EXPIRED",
                    status=410,
                )

        report_context = dict(context.report_context_json) if context else {}
        report_context.update({
            "page_name": str(payload.get("page_name") or "").strip(),
            "filters": payload.get("filters") if isinstance(payload.get("filters"), list) else [],
            "selection_version": int(report_context.get("selection_version") or 0) + (0 if preload else 1),
            "selection_updated_at": timezone.now().isoformat(),
        })
        context_values = {
            "external_identity": external,
            "equipment_id": equipment_id,
            "serial_number": serial_number,
            "mine_site": str(payload.get("minesite") or "").strip(),
            "customer": str(payload.get("customer") or "").strip(),
            "model": str(payload.get("model") or "").strip(),
            "selected_status": str(payload.get("selected_status") or "").strip(),
            "report_context_json": report_context,
            "expires_at": expires_at,
        }
        if context:
            for field, value in context_values.items():
                setattr(context, field, value)
            context.save(update_fields=[*context_values.keys()])
        else:
            context = PowerAppsLaunchContext.objects.create(
                user=request.user,
                configuration=configuration,
                **context_values,
            )
        launch_url = cls.build_launch_url(configuration, context)
        PrimeMoversIntegrationExecutionLog.objects.create(
            user=request.user,
            report=report,
            context=context,
            windows_identity=identity.windows_identity,
            entra_object_id=identity.object_id,
            selected_strategy="dual_workspace",
            powerapps_status="launch_context_created",
            selected_machine=serial_number or equipment_id,
            browser=str(request.META.get("HTTP_USER_AGENT") or "")[:255],
        )
        return context, launch_url

    @staticmethod
    def build_launch_url(configuration: PrimeMoversIntegrationConfiguration, context: PowerAppsLaunchContext) -> str:
        parts = urlsplit(configuration.powerapps_launch_url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query.update({"source": "Mining360", "contextId": str(context.opaque_id)})
        if configuration.powerapps_tenant_id:
            query["tenantId"] = configuration.powerapps_tenant_id
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


class PrimeMoversDiagnosticsService:
    @staticmethod
    def inspect(request, report: PowerBIReport) -> dict:
        identity = CorporateIdentityMappingService.resolve(request.user)
        configuration = getattr(report, "prime_movers_configuration", None)
        blockers = []
        if identity.mapping_status != "validated":
            blockers.append("Microsoft Entra identity mapping is not validated.")
        if not configuration:
            blockers.append("Prime Movers integration configuration is missing.")
        elif not configuration.powerapps_launch_url:
            blockers.append("Official Power Apps launch URL and Environment ID are required.")
        public_base_url = str(getattr(settings, "MINING360_PUBLIC_BASE_URL", "") or "")
        if public_base_url and not public_base_url.startswith("https://"):
            blockers.append("The public Mining 360 URL must use HTTPS outside development.")
        return {
            "identity": {
                "mining360_username": request.user.get_username(),
                "windows_identity": identity.windows_identity,
                "normalized_upn": identity.normalized_upn,
                "entra_tenant_id": identity.tenant_id,
                "entra_object_id": identity.object_id,
                "mapping_status": identity.mapping_status,
            },
            "powerbi": {
                "authentication_mode": report.authentication_mode,
                "report_id": report.report_id,
                "workspace_id": report.workspace_id,
                "token_type": "Embed" if report.authentication_mode == "app_owns_data" else "Aad",
                "powerapps_visual_detected": report.contains_powerapps_visual,
            },
            "powerapps": {
                "app_id": configuration.powerapps_app_id if configuration else "",
                "environment_id": configuration.powerapps_environment_id if configuration else "",
                "launch_url_configured": bool(configuration and configuration.powerapps_launch_url),
                "iframe_enabled": bool(configuration and configuration.iframe_enabled),
                "new_tab_fallback": bool(configuration and configuration.new_tab_fallback),
            },
            "browser": {
                "https": request.is_secure(),
                "web_crypto": "runtime_check_required" if request.is_secure() else "unavailable_without_https",
                "user_agent": str(request.META.get("HTTP_USER_AGENT") or "")[:255],
                "iframe_support": "runtime_check_required",
                "third_party_cookie_status": "runtime_check_required",
            },
            "decision": {
                "recommended_strategy": "dual_workspace",
                "blocking_reasons": blockers,
                "ready": not blockers,
                "readiness_score": max(0, 100 - (25 * len(blockers))),
            },
            "urls": {
                "workspace": reverse("prime-movers-workspace", args=[report.report_id]),
                "corporate_connect": reverse("powerbi-auth-start") + f"?report_id={report.report_id}",
            },
        }
