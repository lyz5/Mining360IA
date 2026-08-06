from __future__ import annotations

import json
import os

from cryptography.fernet import InvalidToken

from .models import AIProvider, AIProviderCredential, SystemIntegrationConfig
from .system_configuration_service import _fernet, decrypt_secrets


ENVIRONMENT_KEYS = {
    "openai": "OPENAI_API_KEY",
    "anthropic_claude": "ANTHROPIC_API_KEY",
    "google_gemini": "GEMINI_API_KEY",
    "glm_5": "GLM_API_KEY",
}


def encrypt_credential(value: str) -> str:
    if not value:
        return ""
    payload = json.dumps({"value": value}, separators=(",", ":")).encode("utf-8")
    return _fernet().encrypt(payload).decode("ascii")


def decrypt_credential(credential: AIProviderCredential) -> str:
    if credential.encrypted_value:
        try:
            payload = _fernet().decrypt(credential.encrypted_value.encode("ascii"))
            return str(json.loads(payload.decode("utf-8")).get("value") or "")
        except (InvalidToken, ValueError, TypeError, json.JSONDecodeError):
            return ""
    reference = str(credential.secret_reference or "")
    if reference.startswith("env:"):
        return os.getenv(reference.split(":", 1)[1], "")
    if reference.startswith("system-integration:"):
        _, code, key = reference.split(":", 2)
        integration = SystemIntegrationConfig.objects.filter(code=code, is_active=True).first()
        return decrypt_secrets(integration).get(key, "") if integration else ""
    return ""


def provider_secret(provider: AIProvider) -> str:
    credential = provider.credentials.filter(active=True).order_by("-updated_at").first()
    if credential:
        value = decrypt_credential(credential).strip()
        if value:
            return value
    return os.getenv(ENVIRONMENT_KEYS.get(provider.code, ""), "").strip()


def credential_configured(provider: AIProvider) -> bool:
    return bool(provider_secret(provider))


def set_provider_secret(provider: AIProvider, value: str, *, credential_type="api_key") -> AIProviderCredential:
    clean = str(value or "").strip()
    if not clean:
        raise ValueError("Credential value is required.")
    credential, _ = AIProviderCredential.objects.get_or_create(
        provider=provider,
        credential_type=credential_type,
    )
    credential.encrypted_value = encrypt_credential(clean)
    credential.secret_reference = ""
    credential.last_four_characters = clean[-4:]
    credential.active = True
    credential.save()
    return credential


def masked_credential(provider: AIProvider) -> str:
    credential = provider.credentials.filter(active=True).order_by("-updated_at").first()
    if not credential_configured(provider):
        return "Not Configured"
    suffix = credential.last_four_characters if credential else ""
    return f"••••••••{suffix}" if suffix else "Configured"
