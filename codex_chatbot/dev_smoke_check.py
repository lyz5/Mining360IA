from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
import uuid
import math

import requests
import urllib3


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Mining360IA.settings")

import django

django.setup()

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client


def main() -> None:
    base_url = os.environ.get("MINING360_DEV_URL", "https://mining360-dev.neemba.local").rstrip("/")
    username = os.environ.get("MINING360_DEV_USER", "papa.diagne@neemba.com")
    question = " ".join(sys.argv[1:]).strip() or "C'est quoi la disponibilité des 785 en YTD"
    user = get_user_model().objects.get(username=username)
    client = Client()
    client.force_login(user)
    session = requests.Session()
    session.cookies.set(
        settings.SESSION_COOKIE_NAME,
        client.cookies[settings.SESSION_COOKIE_NAME].value,
        domain="mining360-dev.neemba.local",
        path="/",
    )
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    page_url = f"{base_url}/codex-chatbot/"
    home = session.get(page_url, verify=False, timeout=20)
    home.raise_for_status()
    csrf = session.cookies.get(settings.CSRF_COOKIE_NAME)
    started = time.monotonic()
    response = session.post(
        f"{base_url}/codex-chatbot/api/runs/",
        json={"question": question, "request_id": str(uuid.uuid4())},
        headers={"X-CSRFToken": csrf, "X-Requested-With": "XMLHttpRequest", "Referer": page_url},
        verify=False,
        timeout=20,
    )
    response.raise_for_status()
    run_id = response.json()["run"]["id"]
    first_verified_seconds = None
    final = None
    max_wait_seconds = max(90, int(getattr(settings, "CODEX_CHATBOT_GENERAL_TIMEOUT_SECONDS", 120)) + 10)
    for _ in range(math.ceil(max_wait_seconds / 0.5)):
        status_response = session.get(
            f"{base_url}/codex-chatbot/api/runs/{run_id}/",
            headers={"X-Requested-With": "XMLHttpRequest"},
            verify=False,
            timeout=20,
        )
        status_response.raise_for_status()
        run = status_response.json()["run"]
        if first_verified_seconds is None and run.get("provisional_message"):
            first_verified_seconds = round(time.monotonic() - started, 2)
        if run.get("terminal"):
            final = run
            break
        time.sleep(0.5)
    if final is None:
        raise TimeoutError(f"The Codex run did not complete within {max_wait_seconds} seconds.")
    result = final.get("result") or {}
    print(json.dumps({
        "submit_status": response.status_code,
        "first_verified_seconds": first_verified_seconds,
        "final_seconds": round(time.monotonic() - started, 2),
        "status": final.get("status"),
        "message": final.get("message"),
        "kind": result.get("kind"),
        "availability": result.get("availability"),
        "context": result.get("context"),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
