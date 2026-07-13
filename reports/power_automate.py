import os

import requests

from .powerbi import _local_powerbi_credentials


HTTP = requests.Session()
HTTP.trust_env = False


def get_flow_url() -> str:
    return (
        os.getenv("POWER_AUTOMATE_DAX_FLOW_URL")
        or _local_powerbi_credentials().get("POWER_AUTOMATE_DAX_FLOW_URL", "")
    ).strip()


def execute_dax_via_flow(payload: dict) -> dict:
    flow_url = get_flow_url()
    if not flow_url:
        raise RuntimeError(
            "POWER_AUTOMATE_DAX_FLOW_URL is not configured. "
            "Create the HTTP-triggered Flow and store its URL in powerbi_credentials.local.json."
        )
    response = HTTP.post(flow_url, json=payload, timeout=300)
    if response.status_code < 200 or response.status_code >= 300:
        raise RuntimeError(
            f"Power Automate DAX flow failed ({response.status_code}): {response.text}"
        )
    try:
        return response.json()
    except Exception:
        return {"raw": response.text}
