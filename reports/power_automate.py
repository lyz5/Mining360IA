import os
import time

import requests

from .powerbi import _local_powerbi_credentials


HTTP = requests.Session()
HTTP.trust_env = False


class PowerAutomateTransientError(RuntimeError):
    """The flow or one of its upstream services is temporarily unavailable."""


def get_flow_url() -> str:
    try:
        from .system_configuration_service import integration_value

        configured_url = integration_value("Power Automate", "dax_flow_url", "", secret=True)
    except Exception:
        configured_url = ""
    return (
        os.getenv("POWER_AUTOMATE_DAX_FLOW_URL")
        or configured_url
        or _local_powerbi_credentials().get("POWER_AUTOMATE_DAX_FLOW_URL", "")
    ).strip()


def execute_dax_via_flow(payload: dict) -> dict:
    flow_url = get_flow_url()
    if not flow_url:
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
            last_error = str(exc)
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
                "Power Automate did not return a result after controlled retries. "
                "Please retry the question in a moment."
            )
        raise RuntimeError(
            f"Power Automate DAX flow failed ({response.status_code}): {response.text}"
        )
    try:
        return response.json()
    except Exception:
        return {"raw": response.text}
