"""Capture and validate the Fleet Inventory chatbot response."""

from __future__ import annotations

import os
import sys
import json
from pathlib import Path

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


def prepared_fleet_conversation() -> tuple[str, str]:
    user = get_user_model().objects.filter(is_superuser=True, is_active=True).first()
    if not user:
        raise RuntimeError("An active superuser is required for the browser check.")
    client = Client()
    client.force_login(user)
    response = client.post(
        "/ai/ask/",
        data=json.dumps({"question": "Give me the Fekola fleet.", "agent_selection": "performance"}),
        content_type="application/json",
    )
    payload = response.json()
    if response.status_code != 200 or not payload.get("ok"):
        raise RuntimeError(f"Fleet conversation setup failed: {response.status_code} {payload}")
    return client.cookies[settings.SESSION_COOKIE_NAME].value, str(payload["conversation_id"])


def assert_fleet_response(page) -> None:
    result = page.evaluate("""
        () => {
            const table = document.querySelector('.ai-fleet-inventory table');
            const headers = table ? [...table.querySelectorAll('thead th')].map(node => node.textContent.trim()) : [];
            return {
                pageOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
                inventoryVisible: Boolean(document.querySelector('.ai-fleet-inventory')),
                headers,
                downloadVisible: Boolean(document.querySelector('.ai-fleet-download')),
                modelSummaryVisible: Boolean(document.querySelector('.ai-fleet-models')),
            };
        }
    """)
    assert not result["pageOverflow"], result
    assert result["inventoryVisible"], result
    assert result["headers"] == ["Site", "Equipment", "Model", "Serial Number"], result
    assert result["downloadVisible"], result
    assert result["modelSummaryVisible"], result


def main() -> None:
    output_dir = PROJECT_ROOT / ".artifacts" / "fleet-inventory-chatbot"
    output_dir.mkdir(parents=True, exist_ok=True)
    cookie, conversation_id = prepared_fleet_conversation()

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
        page.on("response", lambda response: print(f"HTTP {response.status}: {response.url}") if response.status >= 400 else None)
        page.set_default_navigation_timeout(90_000)
        page.set_default_timeout(180_000)
        page.set_viewport_size({"width": 1440, "height": 900})
        page.goto(BASE_URL, wait_until="domcontentloaded")
        page.wait_for_selector(".ai-fleet-inventory", state="visible")
        assert_fleet_response(page)
        page.locator(".ai-fleet-inventory").scroll_into_view_if_needed()
        page.screenshot(path=str(output_dir / "fekola-fleet-desktop-1440x900.png"), animations="disabled")

        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(300)
        assert_fleet_response(page)
        page.locator(".ai-fleet-inventory").scroll_into_view_if_needed()
        page.screenshot(path=str(output_dir / "fekola-fleet-mobile-390x844.png"), animations="disabled")
        browser.close()

    AIConversation.objects.filter(pk=conversation_id).delete()

    print(f"PASS: Fleet Inventory screenshots written to {output_dir}")


if __name__ == "__main__":
    main()
