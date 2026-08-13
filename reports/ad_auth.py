import secrets
from urllib.parse import urlencode

import requests
from django.urls import reverse

from .powerbi import DEFAULT_CLIENT_ID, DEFAULT_TENANT_ID, _local_powerbi_credentials, env_value


AUTHORITY = "https://login.microsoftonline.com"
GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
HTTP = requests.Session()
HTTP.trust_env = False


def ad_config() -> dict:
    from .system_configuration_service import integration_value

    credentials = _local_powerbi_credentials()
    tenant_id = (
        integration_value("Authentication", "tenant_id", "")
        or credentials.get("AZURE_AD_TENANT_ID")
        or credentials.get("POWERBI_TENANT_ID")
        or DEFAULT_TENANT_ID
    )
    client_id = (
        integration_value("Authentication", "client_id", "")
        or credentials.get("AZURE_AD_CLIENT_ID")
        or credentials.get("POWERBI_CLIENT_ID")
        or DEFAULT_CLIENT_ID
    )
    client_secret = (
        integration_value("Authentication", "client_secret", "", secret=True)
        or credentials.get("AZURE_AD_CLIENT_SECRET")
        or credentials.get("POWERBI_CLIENT_SECRET")
    )
    return {
        "tenant_id": tenant_id,
        "client_id": client_id,
        "client_secret": client_secret,
    }


def login_url(request) -> str:
    config = ad_config()
    state = secrets.token_urlsafe(24)
    request.session["azure_ad_state"] = state
    redirect_uri = request.build_absolute_uri(reverse("auth-callback"))
    query = urlencode(
        {
            "client_id": config["client_id"],
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "response_mode": "query",
            "scope": "openid profile email User.Read",
            "state": state,
            "prompt": "select_account",
        }
    )
    return f"{AUTHORITY}/{config['tenant_id']}/oauth2/v2.0/authorize?{query}"


def exchange_code(request, code: str) -> dict:
    config = ad_config()
    if not config.get("client_secret"):
        raise RuntimeError("AZURE_AD_CLIENT_SECRET or POWERBI_CLIENT_SECRET is not configured.")
    redirect_uri = request.build_absolute_uri(reverse("auth-callback"))
    response = HTTP.post(
        f"{AUTHORITY}/{config['tenant_id']}/oauth2/v2.0/token",
        data={
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "scope": "openid profile email User.Read",
        },
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Azure AD token exchange failed ({response.status_code}): {response.text}")
    return response.json()


def fetch_me(access_token: str) -> dict:
    response = HTTP.get(
        f"{GRAPH_ROOT}/me?$select=id,displayName,userPrincipalName,mail,jobTitle",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Microsoft Graph /me failed ({response.status_code}): {response.text}")
    return response.json()


def get_graph_app_token() -> str:
    config = ad_config()
    if not config.get("client_secret"):
        raise RuntimeError("AZURE_AD_CLIENT_SECRET or POWERBI_CLIENT_SECRET is not configured.")
    response = HTTP.post(
        f"{AUTHORITY}/{config['tenant_id']}/oauth2/v2.0/token",
        data={
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
            "grant_type": "client_credentials",
            "scope": "https://graph.microsoft.com/.default",
        },
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Microsoft Graph token failed ({response.status_code}): {response.text}")
    return response.json()["access_token"]


def _escape_filter_value(value: str) -> str:
    return value.replace("'", "''")


def search_directory_users(query: str) -> list[dict]:
    query = (query or "").strip()
    if len(query) < 2:
        return []
    token = get_graph_app_token()
    safe_query = _escape_filter_value(query)
    params = {
        "$top": "15",
        "$select": "id,displayName,userPrincipalName,mail,jobTitle",
        "$filter": (
            f"startswith(displayName,'{safe_query}') "
            f"or startswith(userPrincipalName,'{safe_query}') "
            f"or startswith(mail,'{safe_query}')"
        ),
    }
    response = HTTP.get(
        f"{GRAPH_ROOT}/users",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Microsoft Graph user search failed ({response.status_code}): {response.text}")
    return response.json().get("value", [])
