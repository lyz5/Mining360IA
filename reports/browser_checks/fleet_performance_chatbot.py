"""Capture and validate the Fleet Performance chatbot response."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Mining360IA.settings")

import django

django.setup()

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client
from playwright.sync_api import sync_playwright

from reports.models import AIConversation


BASE_URL = "https://mining360-dev.neemba.local/ai/"
VIEWPORTS = {
    "desktop-1440x900": {"width": 1440, "height": 900},
    "laptop-1366x768": {"width": 1366, "height": 768},
    "tablet-768x1024": {"width": 768, "height": 1024},
    "mobile-390x844": {"width": 390, "height": 844},
}


def prepared_conversation() -> tuple[str, str]:
    user = get_user_model().objects.filter(is_superuser=True, is_active=True).first()
    if not user:
        raise RuntimeError("An active superuser is required for the browser check.")
    client = Client()
    client.force_login(user)
    response = client.post(
        "/ai/ask/",
        data=json.dumps({"question": "Give me the Fekola fleet performance YTD.", "agent_selection": "performance"}),
        content_type="application/json",
    )
    payload = response.json()
    if response.status_code != 200 or not payload.get("ok"):
        raise RuntimeError(f"Fleet Performance setup failed: {response.status_code} {payload}")
    return client.cookies[settings.SESSION_COOKIE_NAME].value, str(payload["conversation_id"])


def assert_response(page) -> None:
    result = page.evaluate("""
        () => ({
            pageOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
            visible: Boolean(document.querySelector('.ai-fleet-performance')),
            metricCount: document.querySelectorAll('.ai-fleet-performance-metrics article').length,
            downloadVisible: Boolean(document.querySelector('.ai-fleet-performance .ai-fleet-download')),
            coverageVisible: Boolean(document.querySelector('.ai-performance-coverage')),
        })
    """)
    assert not result["pageOverflow"], result
    assert result["visible"], result
    assert result["metricCount"] == 6, result
    assert result["downloadVisible"], result
    assert result["coverageVisible"], result


def main() -> None:
    output_dir = PROJECT_ROOT / ".artifacts" / "fleet-performance-chatbot"
    output_dir.mkdir(parents=True, exist_ok=True)
    cookie, conversation_id = prepared_conversation()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        )
        context = browser.new_context(ignore_https_errors=True)
        context.add_cookies([{
            "name": settings.SESSION_COOKIE_NAME,
            "value": cookie,
            "domain": "mining360-dev.neemba.local",
            "path": "/",
            "secure": True,
            "httpOnly": True,
            "sameSite": "Lax",
        }])
        context.add_init_script(
            f"sessionStorage.setItem('mining360-ai-conversation-id', {json.dumps(conversation_id)});"
        )
        page = context.new_page()
        page.on("pageerror", lambda error: print(f"PAGE ERROR: {error}"))
        page.on("console", lambda message: print(f"CONSOLE {message.type}: {message.text}") if message.type in {"error", "warning"} else None)
        page.on("response", lambda response: print(f"HTTP {response.status}: {response.url}") if response.status >= 400 else None)
        page.set_default_navigation_timeout(90_000)
        page.set_default_timeout(180_000)
        page.set_viewport_size(VIEWPORTS["desktop-1440x900"])
        page.goto(BASE_URL, wait_until="domcontentloaded")
        try:
            page.wait_for_selector(".ai-fleet-performance", state="visible", timeout=45_000)
        except Exception:
            page.screenshot(path=str(output_dir / "render-failure.png"), full_page=True)
            print(f"DEBUG URL: {page.url}")
            print(f"DEBUG TITLE: {page.title()}")
            body = page.locator("body").inner_text()[:2000].encode("ascii", "backslashreplace").decode("ascii")
            print(f"DEBUG BODY: {body}")
            raise
        for name, viewport in VIEWPORTS.items():
            page.set_viewport_size(viewport)
            page.wait_for_timeout(250)
            assert_response(page)
            page.locator(".ai-fleet-performance").scroll_into_view_if_needed()
            page.screenshot(path=str(output_dir / f"{name}.png"), animations="disabled")
        browser.close()

    AIConversation.objects.filter(pk=conversation_id).delete()
    print(f"PASS: Fleet Performance screenshots written to {output_dir}")


if __name__ == "__main__":
    main()
