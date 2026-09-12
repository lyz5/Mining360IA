"""Verify that the persisted Pareto Work Type filter refreshes its data."""

from __future__ import annotations

import json
import os
import sys
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


def prepared_conversation() -> tuple[str, str]:
    user = get_user_model().objects.filter(is_superuser=True, is_active=True).first()
    if not user:
        raise RuntimeError("An active superuser is required for the browser check.")
    client = Client()
    client.force_login(user)
    response = client.post(
        "/ai/ask/",
        data=json.dumps({
            "question": "Show the downtime drivers for serial number DNR00153 on YTD",
            "agent_selection": "performance",
        }),
        content_type="application/json",
    )
    payload = response.json()
    if response.status_code != 200 or not payload.get("ok"):
        raise RuntimeError(f"Diagnostics conversation setup failed: {response.status_code} {payload}")
    return client.cookies[settings.SESSION_COOKIE_NAME].value, str(payload["conversation_id"])


def selected_total(page) -> str:
    return page.locator(".ai-downtime-pareto__total strong").text_content().strip()


def main() -> None:
    output_dir = PROJECT_ROOT / ".artifacts" / "availability-work-type"
    output_dir.mkdir(parents=True, exist_ok=True)
    cookie, conversation_id = prepared_conversation()

    try:
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
            page.set_default_navigation_timeout(90_000)
            page.set_default_timeout(120_000)
            page.goto(BASE_URL, wait_until="domcontentloaded")
            page.locator("[data-show-pareto]").click()
            selector = ".ai-downtime-pareto__worktype select"
            page.wait_for_selector(selector, state="visible")

            initial_total = selected_total(page)
            page.locator(selector).select_option("Planned")
            page.wait_for_function(
                "args => document.querySelector(args.selector)?.value === 'Planned' "
                "&& document.querySelector('.ai-downtime-pareto__total strong')?.textContent.trim() !== args.previousTotal",
                arg={"selector": selector, "previousTotal": initial_total},
            )
            planned_total = selected_total(page)
            page.screenshot(path=str(output_dir / "pareto-planned.png"), animations="disabled")

            page.locator(selector).select_option("Unplanned")
            page.wait_for_function(
                "args => document.querySelector(args.selector)?.value === 'Unplanned' "
                "&& document.querySelector('.ai-downtime-pareto__total strong')?.textContent.trim() !== args.previousTotal",
                arg={"selector": selector, "previousTotal": planned_total},
            )
            unplanned_total = selected_total(page)
            page.screenshot(path=str(output_dir / "pareto-unplanned.png"), animations="disabled")

            assert planned_total != unplanned_total, (planned_total, unplanned_total)
            browser.close()
    finally:
        AIConversation.objects.filter(pk=conversation_id).delete()

    print(f"PASS: Planned={planned_total}; Unplanned={unplanned_total}")


if __name__ == "__main__":
    main()
