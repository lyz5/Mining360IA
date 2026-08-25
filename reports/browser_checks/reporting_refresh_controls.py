"""Browser validation for per-report Power BI refresh controls."""

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


def authenticated_session_cookie() -> str:
    user = get_user_model().objects.filter(is_superuser=True, is_active=True).first()
    if not user:
        raise RuntimeError("An active superuser is required for the browser check.")
    client = Client()
    client.force_login(user)
    return client.cookies[settings.SESSION_COOKIE_NAME].value


def main() -> None:
    output_dir = Path(".artifacts/reporting-refresh")
    output_dir.mkdir(parents=True, exist_ok=True)
    cookie = authenticated_session_cookie()

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
        page = context.new_page()

        for width, height in ((1440, 900), (390, 844)):
            page.set_viewport_size({"width": width, "height": height})
            page.goto("https://mining360-dev.neemba.local/reporting/", wait_until="domcontentloaded")
            page.wait_for_selector("[data-report-card]", state="visible", timeout=60_000)
            result = page.evaluate("""
                () => ({
                    cards: document.querySelectorAll('[data-report-card]').length,
                    buttons: document.querySelectorAll('[data-report-refresh]').length,
                    missingLabels: Array.from(document.querySelectorAll('[data-report-refresh]'))
                        .filter((button) => !button.getAttribute('aria-label')).length,
                    pageOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
                })
            """)
            if result["cards"] < 1 or result["buttons"] != result["cards"]:
                raise AssertionError(f"Missing refresh controls at {width}x{height}: {result}")
            if result["missingLabels"] or result["pageOverflow"]:
                raise AssertionError(f"Accessibility or overflow failure at {width}x{height}: {result}")
            page.screenshot(path=str(output_dir / f"reporting-refresh-{width}x{height}.png"), full_page=True)
            print(f"PASS layout {width}x{height}")

        page.set_viewport_size({"width": 1440, "height": 900})
        page.goto("https://mining360-dev.neemba.local/reporting/", wait_until="domcontentloaded")
        page.click(".js-toggle-config-menu")
        page.wait_for_selector("#config-submenu", state="visible")
        submenu = page.locator("#config-submenu")
        if submenu.locator('a[href="/data/"]').count() != 1:
            raise AssertionError("Data is not available inside the Config submenu.")
        if submenu.locator('a[href="/data-sources/"]').count() != 1:
            raise AssertionError("Sources is not available inside the Config submenu.")
        page.screenshot(path=str(output_dir / "config-menu-data-sources.png"), full_page=True)
        print("PASS Data and Sources inside Config menu")

        def mock_refresh(route) -> None:
            route.fulfill(
                status=202,
                content_type="application/json",
                body=json.dumps({
                    "ok": True,
                    "dataset_id": route.request.url.split("/")[-3],
                    "status": "Refreshing",
                    "is_refreshing": True,
                    "last_refresh": "2026-08-20 08:00 AM",
                }),
            )

        page.route("**/reporting/reports/*/refresh/", mock_refresh)
        first_button = page.locator("[data-report-refresh]:not([disabled])").first
        report_id = first_button.evaluate("button => button.closest('[data-report-card]').dataset.reportId")
        card = page.locator(f'[data-report-card][data-report-id="{report_id}"]')
        button = card.locator("[data-report-refresh]")
        button.click()
        card.locator("[data-status-label]").wait_for(state="visible", timeout=10_000)
        page.wait_for_function(
            "element => element.textContent.trim() === 'Refreshing'",
            arg=card.locator("[data-status-label]").element_handle(),
            timeout=10_000,
        )
        if card.locator("[data-status-label]").inner_text() != "Refreshing":
            raise AssertionError("The card did not enter the Refreshing state after the request.")
        if not button.is_disabled():
            raise AssertionError("The refresh button remained enabled while refresh was running.")
        if "Refresh in progress" not in card.locator("[data-status-detail]").inner_text():
            raise AssertionError("The in-progress helper message is missing.")
        page.screenshot(path=str(output_dir / "reporting-refresh-active.png"), full_page=True)
        print("PASS interactive Refreshing state")
        browser.close()


if __name__ == "__main__":
    main()
