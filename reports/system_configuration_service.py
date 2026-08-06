from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlparse

import requests
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import SystemIntegrationConfig, SystemParameter


MASKED_SECRET = "********"
HTTP = requests.Session()
HTTP.trust_env = False


def _as_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


INTEGRATION_SCHEMAS = {
    "Power BI": {
        "provider": "Microsoft Power BI",
        "fields": [
            {"key": "workspace_id", "label": "Workspace ID", "type": "text", "required": True},
            {"key": "workspace_name", "label": "Workspace Name", "type": "text"},
            {"key": "tenant_id", "label": "Tenant ID", "type": "text", "required": True},
            {"key": "client_id", "label": "Client ID", "type": "text", "required": True},
            {"key": "client_secret", "label": "Client Secret", "type": "password", "secret": True, "required": True},
            {"key": "api_root", "label": "REST API Root", "type": "url", "default": "https://api.powerbi.com/v1.0/myorg"},
            {"key": "scope", "label": "OAuth Scope", "type": "text", "default": "https://analysis.windows.net/powerbi/api/.default"},
            {"key": "effective_roles", "label": "Default RLS Roles", "type": "text"},
            {"key": "effective_username", "label": "Default Effective Username", "type": "text"},
            {"key": "report_cache_seconds", "label": "Report Cache (seconds)", "type": "number", "default": 300},
        ],
    },
    "Power Automate": {
        "provider": "Microsoft Power Automate",
        "fields": [
            {"key": "dax_flow_url", "label": "DAX Flow URL", "type": "password", "secret": True, "required": True},
            {"key": "timeout_seconds", "label": "Timeout (seconds)", "type": "number", "default": 300},
            {"key": "retry_count", "label": "Retry Count", "type": "number", "default": 1},
        ],
    },
    "OpenAI": {
        "provider": "OpenAI",
        "fields": [
            {"key": "api_key", "label": "API Key", "type": "password", "secret": True, "required": True},
            {"key": "admin_api_key", "label": "Organization Admin Key", "type": "password", "secret": True},
            {"key": "organization_id", "label": "Organization ID", "type": "text"},
            {"key": "project_id", "label": "Project ID", "type": "text"},
            {"key": "default_model", "label": "Default Model", "type": "text", "default": "gpt-4.1-mini"},
            {"key": "api_base", "label": "API Base URL", "type": "url", "default": "https://api.openai.com/v1"},
            {"key": "timeout_seconds", "label": "Timeout (seconds)", "type": "number", "default": 120},
        ],
    },
    "Database": {
        "provider": "SQL Database",
        "fields": [
            {"key": "engine", "label": "Engine", "type": "select", "options": ["SQL Server", "PostgreSQL", "MySQL", "Snowflake", "Other"], "default": "SQL Server"},
            {"key": "host", "label": "Host", "type": "text", "required": True},
            {"key": "port", "label": "Port", "type": "number"},
            {"key": "database", "label": "Database", "type": "text", "required": True},
            {"key": "schema", "label": "Schema", "type": "text", "default": "dbo"},
            {"key": "username", "label": "Username", "type": "text"},
            {"key": "password", "label": "Password", "type": "password", "secret": True},
            {"key": "driver", "label": "Driver", "type": "text"},
            {"key": "connection_timeout", "label": "Connection Timeout", "type": "number", "default": 30},
            {"key": "encrypt", "label": "Encrypt Connection", "type": "boolean", "default": True},
            {"key": "trust_server_certificate", "label": "Trust Server Certificate", "type": "boolean", "default": False},
        ],
    },
    "Data Source": {
        "provider": "External Source",
        "fields": [
            {"key": "source_type", "label": "Source Type", "type": "text", "required": True},
            {"key": "endpoint", "label": "Endpoint or Host", "type": "text", "required": True},
            {"key": "database", "label": "Database / Catalog", "type": "text"},
            {"key": "username", "label": "Username", "type": "text"},
            {"key": "password", "label": "Password / Token", "type": "password", "secret": True},
            {"key": "driver", "label": "Driver", "type": "text"},
        ],
    },
    "Storage": {
        "provider": "File Storage",
        "fields": [
            {"key": "root_path", "label": "Root Path", "type": "text", "required": True},
            {"key": "retention_days", "label": "Retention Days", "type": "number", "default": 365},
            {"key": "allowed_extensions", "label": "Allowed Extensions", "type": "text"},
            {"key": "max_file_size_mb", "label": "Maximum File Size (MB)", "type": "number", "default": 100},
        ],
    },
    "Authentication": {
        "provider": "Microsoft Entra ID",
        "fields": [
            {"key": "tenant_id", "label": "Tenant ID", "type": "text", "required": True},
            {"key": "client_id", "label": "Client ID", "type": "text", "required": True},
            {"key": "client_secret", "label": "Client Secret", "type": "password", "secret": True},
            {"key": "redirect_uri", "label": "Redirect URI", "type": "url"},
            {"key": "allowed_domains", "label": "Allowed Email Domains", "type": "text"},
        ],
    },
    "Notification": {
        "provider": "Notification Provider",
        "fields": [
            {"key": "webhook_url", "label": "Webhook URL", "type": "password", "secret": True},
            {"key": "sender", "label": "Sender", "type": "text"},
            {"key": "enabled", "label": "Enabled", "type": "boolean", "default": False},
        ],
    },
    "Other": {"provider": "Custom", "fields": []},
}


DEFAULT_PARAMETERS = [
    ("application-name", "Organization", "Application Name", "Text", "Mining360"),
    ("company-name", "Organization", "Company Name", "Text", "To configure"),
    ("default-timezone", "Localization", "Default Timezone", "Text", "UTC"),
    ("default-language", "Localization", "Default Language", "Text", "en"),
    ("default-currency", "Localization", "Default Currency", "Text", "USD"),
    ("environment-name", "Runtime", "Environment", "Text", "development"),
    ("default-query-timeout", "Runtime", "Default Query Timeout", "Duration", 300),
    ("default-cache-duration", "Runtime", "Default Cache Duration", "Duration", 300),
    ("default-page-size", "Runtime", "Default Page Size", "Integer", 50),
    ("maximum-export-rows", "Runtime", "Maximum Export Rows", "Integer", 100000),
]


def _fernet():
    explicit_key = os.getenv("MINING360_CONFIG_ENCRYPTION_KEY", "").strip()
    if explicit_key:
        return Fernet(explicit_key.encode("ascii"))
    digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secrets(values: dict) -> str:
    if not values:
        return ""
    raw = json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return _fernet().encrypt(raw).decode("ascii")


def decrypt_secrets(item: SystemIntegrationConfig) -> dict:
    if not item.encrypted_secrets:
        return {}
    try:
        payload = _fernet().decrypt(item.encrypted_secrets.encode("ascii"))
        value = json.loads(payload.decode("utf-8"))
        return value if isinstance(value, dict) else {}
    except (InvalidToken, ValueError, TypeError, json.JSONDecodeError):
        return {}


def schema_payload():
    return [
        {"type": key, "provider": value["provider"], "fields": value["fields"]}
        for key, value in INTEGRATION_SCHEMAS.items()
    ]


def integration_payload(item, *, include_schema=True):
    settings_values = dict(item.settings_json or {})
    for secret_key in item.configured_secret_keys or []:
        settings_values[secret_key] = MASKED_SECRET
    payload = {
        "id": item.pk,
        "code": item.code,
        "name": item.name,
        "integration_type": item.integration_type,
        "provider": item.provider,
        "description": item.description,
        "settings": settings_values,
        "configured_secret_keys": item.configured_secret_keys or [],
        "is_default": item.is_default,
        "is_active": item.is_active,
        "status": item.status,
        "last_verified_at": item.last_verified_at.isoformat() if item.last_verified_at else "",
        "last_message": item.last_message,
        "updated_at": item.updated_at.isoformat() if item.updated_at else "",
    }
    if include_schema:
        payload["fields"] = INTEGRATION_SCHEMAS.get(item.integration_type, INTEGRATION_SCHEMAS["Other"])["fields"]
    return payload


def _read_json(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _environment_or_file(env_name, file_values, default=""):
    return os.getenv(env_name, "").strip() or str(file_values.get(env_name, default) or "").strip()


@transaction.atomic
def ensure_portable_configuration():
    base_dir = Path(settings.BASE_DIR)
    powerbi_file = _read_json(base_dir / "powerbi_credentials.local.json")
    sql_file = _read_json(base_dir / "mining360_sqlserver.local.json")

    connector_seeds = [
        {
            "code": "power-bi-default", "name": "Power BI", "integration_type": "Power BI",
            "settings": {
                "workspace_id": _environment_or_file("POWERBI_WORKSPACE_ID", powerbi_file),
                "workspace_name": _environment_or_file("POWERBI_WORKSPACE_NAME", powerbi_file),
                "tenant_id": _environment_or_file("POWERBI_TENANT_ID", powerbi_file),
                "client_id": _environment_or_file("POWERBI_CLIENT_ID", powerbi_file),
                "api_root": _environment_or_file("POWERBI_API_ROOT", powerbi_file, "https://api.powerbi.com/v1.0/myorg"),
                "scope": _environment_or_file("POWERBI_SCOPE", powerbi_file, "https://analysis.windows.net/powerbi/api/.default"),
                "effective_roles": _environment_or_file("POWERBI_EFFECTIVE_ROLES", powerbi_file),
                "effective_username": _environment_or_file("POWERBI_EFFECTIVE_USERNAME", powerbi_file),
                "report_cache_seconds": 300,
            },
            "secrets": {"client_secret": _environment_or_file("POWERBI_CLIENT_SECRET", powerbi_file)},
        },
        {
            "code": "power-automate-dax", "name": "Power Automate DAX", "integration_type": "Power Automate",
            "settings": {"timeout_seconds": 300, "retry_count": 1},
            "secrets": {"dax_flow_url": _environment_or_file("POWER_AUTOMATE_DAX_FLOW_URL", powerbi_file)},
        },
        {
            "code": "openai-default", "name": "OpenAI", "integration_type": "OpenAI",
            "settings": {
                "organization_id": os.getenv("OPENAI_ORGANIZATION_ID", ""),
                "project_id": os.getenv("OPENAI_PROJECT_ID", ""),
                "default_model": _environment_or_file("OPENAI_MODEL", powerbi_file, "gpt-4.1-mini"),
                "api_base": os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1"),
                "timeout_seconds": 120,
            },
            "secrets": {
                "api_key": _environment_or_file("OPENAI_API_KEY", powerbi_file),
                "admin_api_key": os.getenv("OPENAI_ADMIN_API_KEY", ""),
            },
        },
        {
            "code": "mining360-database", "name": "Mining360 Database", "integration_type": "Database",
            "settings": {
                "engine": "SQL Server",
                "host": _environment_or_file("MINING360_SQL_SERVER", sql_file),
                "port": int(_environment_or_file("MINING360_SQL_PORT", sql_file, "1433") or 1433),
                "database": _environment_or_file("MINING360_SQL_DATABASE", sql_file),
                "schema": "dbo",
                "username": _environment_or_file("MINING360_SQL_USER", sql_file),
                "driver": _environment_or_file("MINING360_SQL_DRIVER", sql_file),
                "connection_timeout": 30,
                "encrypt": True,
                "trust_server_certificate": False,
            },
            "secrets": {"password": _environment_or_file("MINING360_SQL_PASSWORD", sql_file)},
        },
        {
            "code": "resource-library", "name": "Resource Library", "integration_type": "Storage",
            "settings": {
                "root_path": os.getenv("RESOURCE_LIBRARY_PATH", str(base_dir / "resource_library")),
                "retention_days": 365,
                "allowed_extensions": "pdf,docx,pptx,xlsx,txt,md",
                "max_file_size_mb": 100,
            },
            "secrets": {},
        },
    ]

    for seed in connector_seeds:
        item, created = SystemIntegrationConfig.objects.get_or_create(
            code=seed["code"],
            defaults={
                "name": seed["name"],
                "integration_type": seed["integration_type"],
                "provider": INTEGRATION_SCHEMAS[seed["integration_type"]]["provider"],
                "description": f"Portable {seed['integration_type']} configuration.",
                "settings_json": seed["settings"],
                "is_default": True,
                "status": "Configured" if any(seed["settings"].values()) else "Not Configured",
            },
        )
        if created:
            secrets = {key: value for key, value in seed["secrets"].items() if value}
            item.encrypted_secrets = encrypt_secrets(secrets)
            item.configured_secret_keys = sorted(secrets)
            item.save(update_fields=["encrypted_secrets", "configured_secret_keys", "updated_at"])

    for key, category, label, value_type, default in DEFAULT_PARAMETERS:
        SystemParameter.objects.get_or_create(
            key=key,
            defaults={
                "category": category,
                "label": label,
                "value_type": value_type,
                "value_json": default,
                "default_value_json": default,
                "is_active": True,
            },
        )


def save_integration(item, payload, user=None):
    integration_type = str(payload.get("integration_type") or item.integration_type or "Other")
    if integration_type not in INTEGRATION_SCHEMAS:
        raise ValueError("Unsupported integration type.")
    schema = INTEGRATION_SCHEMAS[integration_type]
    incoming = payload.get("settings") or {}
    if not isinstance(incoming, dict):
        raise ValueError("Settings must be an object.")
    existing_secrets = decrypt_secrets(item) if item.pk else {}
    clean_settings = {}
    secret_values = dict(existing_secrets)
    for field in schema["fields"]:
        key = field["key"]
        value = incoming.get(key, field.get("default", ""))
        if field.get("secret"):
            if value not in (None, "", MASKED_SECRET):
                secret_values[key] = str(value)
            continue
        if field["type"] == "number" and value not in (None, ""):
            value = int(value)
        elif field["type"] == "boolean":
            value = _as_bool(value, field.get("default", False))
        clean_settings[key] = value
        if field.get("required") and value in (None, ""):
            raise ValueError(f"{field['label']} is required.")
    for field in schema["fields"]:
        if field.get("secret") and field.get("required") and not secret_values.get(field["key"]):
            raise ValueError(f"{field['label']} is required.")

    item.code = str(payload.get("code") or item.code or "").strip().lower()
    item.name = str(payload.get("name") or item.name or "").strip()
    item.integration_type = integration_type
    item.provider = str(payload.get("provider") or schema["provider"]).strip()
    item.description = str(payload.get("description") or "").strip()
    item.settings_json = clean_settings
    item.encrypted_secrets = encrypt_secrets(secret_values)
    item.configured_secret_keys = sorted(key for key, value in secret_values.items() if value)
    item.is_default = _as_bool(payload.get("is_default"), item.is_default)
    item.is_active = _as_bool(payload.get("is_active"), True)
    item.status = "Configured" if item.is_active else "Disabled"
    item.updated_by = user if getattr(user, "is_authenticated", False) else None
    if not item.pk:
        item.created_by = item.updated_by
    if not item.code or not item.name:
        raise ValueError("Code and name are required.")
    if item.is_default:
        SystemIntegrationConfig.objects.filter(
            integration_type=integration_type, is_default=True,
        ).exclude(pk=item.pk).update(is_default=False)
    item.save()
    return item


def integration_value(integration_type, key, default="", *, code=None, secret=False):
    try:
        queryset = SystemIntegrationConfig.objects.filter(
            integration_type=integration_type, is_active=True,
        )
        item = queryset.filter(code=code).first() if code else queryset.filter(is_default=True).first()
        item = item or queryset.first()
        if not item:
            return default
        if secret:
            return decrypt_secrets(item).get(key, default)
        return (item.settings_json or {}).get(key, default)
    except Exception:
        return default


def parameter_value(key, default=None):
    try:
        item = SystemParameter.objects.filter(key=key, is_active=True).first()
        return item.value_json if item and item.value_json is not None else default
    except Exception:
        return default


def test_integration(item):
    settings_values = item.settings_json or {}
    secrets = decrypt_secrets(item)
    started = timezone.now()
    try:
        if item.integration_type == "Power BI":
            tenant = settings_values.get("tenant_id")
            client = settings_values.get("client_id")
            secret = secrets.get("client_secret")
            workspace = settings_values.get("workspace_id")
            token_response = HTTP.post(
                f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
                data={"grant_type": "client_credentials", "client_id": client, "client_secret": secret,
                      "scope": settings_values.get("scope") or "https://analysis.windows.net/powerbi/api/.default"},
                timeout=30,
            )
            token_response.raise_for_status()
            token = token_response.json()["access_token"]
            api_root = (settings_values.get("api_root") or "https://api.powerbi.com/v1.0/myorg").rstrip("/")
            response = HTTP.get(f"{api_root}/groups/{workspace}", headers={"Authorization": f"Bearer {token}"}, timeout=30)
            response.raise_for_status()
            message = f"Connected to workspace: {response.json().get('name') or workspace}"
        elif item.integration_type == "OpenAI":
            api_key = secrets.get("api_key")
            api_base = (settings_values.get("api_base") or "https://api.openai.com/v1").rstrip("/")
            response = HTTP.get(f"{api_base}/models", headers={"Authorization": f"Bearer {api_key}"}, timeout=30)
            response.raise_for_status()
            message = "OpenAI API connection successful."
        elif item.integration_type == "Power Automate":
            flow_url = secrets.get("dax_flow_url", "")
            parsed = urlparse(flow_url)
            if parsed.scheme != "https" or not parsed.netloc:
                raise ValueError("A valid HTTPS Flow URL is required.")
            message = "Flow URL is configured. Execution is tested with the DAX test tool."
        elif item.integration_type == "Storage":
            path = Path(str(settings_values.get("root_path") or ""))
            if not path.exists() or not path.is_dir():
                raise ValueError("Storage path does not exist or is not a directory.")
            message = f"Storage path is available: {path}"
        elif item.integration_type == "Database":
            from .sqlserver import connect
            with connect(
                server=settings_values.get("host"), database=settings_values.get("database"),
                user=settings_values.get("username") or None, password=secrets.get("password") or None,
                port=settings_values.get("port") or None,
            ) as connection:
                row = connection.cursor().execute("SELECT @@SERVERNAME, DB_NAME()").fetchone()
            message = f"Connected to {row[0]} / {row[1]}"
        else:
            endpoint = str(settings_values.get("endpoint") or "")
            if endpoint.startswith("http"):
                response = HTTP.get(endpoint, timeout=15)
                if response.status_code >= 500:
                    raise ValueError(f"Endpoint returned HTTP {response.status_code}.")
            message = "Configuration is structurally valid."
        item.status = "Connected"
        item.last_message = message
    except Exception as exc:
        item.status = "Failed"
        item.last_message = str(exc)[:2000]
    item.last_verified_at = started
    item.save(update_fields=["status", "last_message", "last_verified_at", "updated_at"])
    return item.status == "Connected", item.last_message
