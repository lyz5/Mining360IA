from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from .models import PlatformUser, UserExternalIdentity


class CorporateIdentityMappingError(RuntimeError):
    def __init__(self, message: str, *, code: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


class CorporateIdentityMappingService:
    @staticmethod
    @transaction.atomic
    def validate_from_microsoft_account(user, account: dict) -> UserExternalIdentity:
        platform_user = PlatformUser.objects.select_for_update().get(django_user=user)
        tenant_id = str(account.get("tenant_id") or "").strip()
        object_id = str(account.get("object_id") or "").strip()
        upn = str(account.get("username") or "").strip().casefold()
        if not tenant_id or not object_id or not upn:
            raise CorporateIdentityMappingError(
                "Microsoft did not return a complete corporate identity.",
                code="ENTRA_IDENTITY_INCOMPLETE",
            )
        if platform_user.user_principal_name.casefold() != upn:
            raise CorporateIdentityMappingError(
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
            raise CorporateIdentityMappingError(
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
