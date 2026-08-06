from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.utils import timezone

from deployment.models import DeploymentCredential


def _deployment_fernet():
    configured = os.getenv("MINING360_DEPLOYMENT_ENCRYPTION_KEY", "").strip()
    if configured:
        return Fernet(configured.encode("ascii"))
    if not settings.DEBUG:
        raise RuntimeError("MINING360_DEPLOYMENT_ENCRYPTION_KEY is required outside development.")
    digest = hashlib.sha256(f"deployment:{settings.SECRET_KEY}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def set_credential_secret(credential: DeploymentCredential, value: str):
    clean = str(value or "")
    if not clean.strip():
        raise ValueError("Credential value is required.")
    payload = json.dumps({"value": clean}, separators=(",", ":")).encode()
    credential.encrypted_secret = _deployment_fernet().encrypt(payload).decode("ascii")
    credential.secret_reference = ""
    credential.last_four_characters = clean.strip()[-4:]
    credential.last_rotated_at = timezone.now()
    credential.save(update_fields=["encrypted_secret", "secret_reference", "last_four_characters", "last_rotated_at", "updated_at"])


def credential_secret(credential: DeploymentCredential | None) -> str:
    if not credential or not credential.active:
        return ""
    if credential.secret_reference.startswith("env:"):
        return os.getenv(credential.secret_reference.split(":", 1)[1], "")
    if credential.secret_reference.startswith("file:"):
        configured_root = os.getenv("MINING360_DEPLOYMENT_SECRET_ROOT", "").strip()
        allowed_root = Path(configured_root).expanduser() if configured_root else Path.home() / ".ssh"
        allowed_root = allowed_root.resolve()
        candidate = Path(credential.secret_reference.split(":", 1)[1]).expanduser().resolve()
        if not candidate.is_relative_to(allowed_root) or not candidate.is_file():
            return ""
        try:
            return candidate.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return ""
    if not credential.encrypted_secret:
        return ""
    try:
        raw = _deployment_fernet().decrypt(credential.encrypted_secret.encode("ascii"))
        return str(json.loads(raw.decode()).get("value") or "")
    except (InvalidToken, ValueError, TypeError, json.JSONDecodeError):
        return ""


def masked_credential(credential: DeploymentCredential | None) -> str:
    if not credential or not (credential.encrypted_secret or credential.secret_reference):
        return "Not Configured"
    return f"••••••••{credential.last_four_characters}" if credential.last_four_characters else "Configured"
