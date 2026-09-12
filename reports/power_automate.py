import os
import time

import requests

from .powerbi import _local_powerbi_credentials


HTTP = requests.Session()
HTTP.trust_env = False


class PowerAutomateTransientError(RuntimeError):
    """The flow or one of its upstream services is temporarily unavailable."""


def _diagnostic_reference(response) -> str:
    if response is None:
        return ""
    for header in (
        "x-ms-request-id", "x-ms-correlation-request-id", "request-id",
        "client-request-id", "x-azure-ref",
    ):
        value = str(response.headers.get(header) or "").strip()
        if value:
            return f", reference {value}"
    return ""


AFTERMARKET_DATASET_NAMES = {
    "mine logistics & aftermarket",
}
LOGISTICS_DATASET_NAMES = {
    "mine logistics report",
}


def _uses_aftermarket_flow(dataset_name: str) -> bool:
    return str(dataset_name or "").strip().casefold() in AFTERMARKET_DATASET_NAMES


def _uses_logistics_flow(dataset_name: str) -> bool:
    return str(dataset_name or "").strip().casefold() in LOGISTICS_DATASET_NAMES


def get_flow_url(dataset_name: str = "") -> str:
    aftermarket = _uses_aftermarket_flow(dataset_name)
    logistics = _uses_logistics_flow(dataset_name)
    if logistics:
        config_key = "logistics_dax_flow_url"
        environment_key = "POWER_AUTOMATE_LOGISTICS_DAX_FLOW_URL"
    elif aftermarket:
        config_key = "aftermarket_dax_flow_url"
        environment_key = "POWER_AUTOMATE_AFTERMARKET_DAX_FLOW_URL"
    else:
        config_key = "dax_flow_url"
        environment_key = "POWER_AUTOMATE_DAX_FLOW_URL"
    try:
        from .system_configuration_service import integration_value

        configured_url = integration_value("Power Automate", config_key, "", secret=True)
    except Exception:
        configured_url = ""
    return (
        os.getenv(environment_key)
        or configured_url
        or _local_powerbi_credentials().get(environment_key, "")
    ).strip()


def execute_dax_via_flow(payload: dict) -> dict:
    dataset_name = str(payload.get("datasetName") or "").strip()
    flow_url = get_flow_url(dataset_name)
    if not flow_url:
        if _uses_logistics_flow(dataset_name):
            raise RuntimeError(
                "inspectData3 is not configured for Mine Logistics Report. "
                "Set POWER_AUTOMATE_LOGISTICS_DAX_FLOW_URL or configure the "
                "Mine Logistics DAX Flow URL in System Configuration."
            )
        if _uses_aftermarket_flow(dataset_name):
            raise RuntimeError(
                "inspectData2 is not configured for Mine Logistics & AfterMarket. "
                "Set POWER_AUTOMATE_AFTERMARKET_DAX_FLOW_URL or configure the "
                "AfterMarket DAX Flow URL in System Configuration."
            )
        raise RuntimeError(
            "POWER_AUTOMATE_DAX_FLOW_URL is not configured. "
            "Create the HTTP-triggered Flow and store its URL in powerbi_credentials.local.json."
        )
    try:
        from .system_configuration_service import integration_value

        timeout = int(integration_value("Power Automate", "timeout_seconds", 300) or 300)
        retry_count = int(integration_value("Power Automate", "retry_count", 2) or 2)
    except Exception:
        timeout = 300
        retry_count = 2
    response = None
    last_error = None
    for attempt in range(max(0, min(retry_count, 3)) + 1):
        try:
            response = HTTP.post(flow_url, json=payload, timeout=timeout)
            if response.status_code not in {429, 502, 503, 504}:
                break
            last_error = f"HTTP {response.status_code}: {response.text}"
        except requests.RequestException as exc:
            # Request exception text may contain the signed Flow URL. Keep diagnostics secret-safe.
            last_error = exc.__class__.__name__
            response = None
        if attempt < retry_count:
            time.sleep(min(2 ** attempt, 4))
    if response is None:
        raise PowerAutomateTransientError(
            "Power Automate DAX flow is temporarily unavailable after retries: "
            f"{last_error or 'connection failed'}"
        )
    if response.status_code < 200 or response.status_code >= 300:
        if response.status_code in {429, 502, 503, 504}:
            raise PowerAutomateTransientError(
                f"Power Automate returned HTTP {response.status_code} after controlled retries"
                f"{_diagnostic_reference(response)}. Please retry the question in a moment."
            )
        raise RuntimeError(
            f"Power Automate DAX flow failed ({response.status_code}): {response.text}"
        )
    try:
        return response.json()
    except Exception:
        return {"raw": response.text}
