"""Capture the real development Business Command Center with governed database data."""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from wsgiref.simple_server import make_server


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Mining360IA.settings")
for flag in (
    "ENABLE_BUSINESS_COMMAND_CENTER",
    "ENABLE_BUSINESS_COMMAND_CENTER_CUSTOMERS",
    "ENABLE_BUSINESS_COMMAND_CENTER_COUNTRIES",
    "ENABLE_BUSINESS_COMMAND_CENTER_KEY_ACCOUNTS",
    "ENABLE_BUSINESS_COMMAND_CENTER_LAST_VISIT",
    "ENABLE_BUSINESS_COMMAND_CENTER_ATTENTION",
    "ENABLE_BUSINESS_COMMAND_CENTER_WATCHLIST",
    "ENABLE_BUSINESS_COMMAND_CENTER_PRESENTATION_MODE",
):
    os.environ[flag] = "Production"

import django

django.setup()

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.handlers import StaticFilesHandler
from django.core.wsgi import get_wsgi_application
from django.test import Client
from playwright.sync_api import sync_playwright


OUTPUT = PROJECT_ROOT / "docs" / "screenshots" / "business-command-center-2026-09-14"
BASE_URL = "http://127.0.0.1:8125/business-review/command-center/"


def session_cookie() -> str:
    user_model = get_user_model()
    user = user_model.objects.filter(username="papa.diagne@neemba.com", is_active=True).first()
    user = user or user_model.objects.filter(is_superuser=True, is_active=True).first()
    if user is None:
        raise RuntimeError("No active authorized user is available for the capture.")
    client = Client()
    client.force_login(user)
    return client.cookies[settings.SESSION_COOKIE_NAME].value


def capture_section(page, selector: str, filename: str) -> None:
    section = page.locator(selector)
    section.scroll_into_view_if_needed()
    page.wait_for_timeout(250)
    section.screenshot(path=str(OUTPUT / filename))


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    cookie_value = session_cookie()
    server = make_server("127.0.0.1", 8125, StaticFilesHandler(get_wsgi_application()))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    errors: list[str] = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            )
            context = browser.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
            context.add_cookies([{
                "name": settings.SESSION_COOKIE_NAME,
                "value": cookie_value,
                "domain": "127.0.0.1",
                "path": "/",
                "httpOnly": True,
                "sameSite": "Lax",
            }])
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(BASE_URL, wait_until="networkidle", timeout=120_000)
            page.wait_for_selector("[data-content]:visible", timeout=120_000)
            page.wait_for_function(
                """() => {
                    const machine = document.querySelector('[data-machine-status]');
                    const parts = document.querySelector('[data-parts-status]');
                    return machine && parts && machine.hidden && parts.hidden;
                }""",
                timeout=120_000,
            )

            page.screenshot(path=str(OUTPUT / "01-command-center-full-page.png"), full_page=True)
            capture_section(page, ".bcc-header", "02-header-and-controls.png")
            capture_section(page, ".bcc-first-view", "03-executive-revenue-overview.png")
            capture_section(page, ".bcc-machine-sales", "04-machines-sold.png")
            capture_section(page, ".bcc-parts-sales", "05-parts-major-class.png")
            capture_section(page, ".bcc-change-row", "06-what-changed-and-last-visit.png")
            capture_section(page, ".bcc-analytics", "07-revenue-trend-mix-bridge.png")
            capture_section(page, ".bcc-sales-review", "08-sales-performance-business-lines.png")

            page.locator('[data-sales-tab="countries"]').click()
            capture_section(page, ".bcc-sales-review", "09-sales-performance-countries.png")
            page.locator('[data-sales-tab="customers"]').click()
            capture_section(page, ".bcc-sales-review", "10-sales-performance-customers.png")

            page.locator('[data-dimension="key_accounts"]').click()
            capture_section(page, ".bcc-explorer", "11-key-account-revenue-leaders.png")
            first_entity = page.locator("[data-dimension-table] [data-entity-id]").first
            if first_entity.count():
                first_entity.click()
                page.wait_for_selector("[data-drawer]:visible")
                page.screenshot(path=str(OUTPUT / "12-key-account-360-drawer.png"), full_page=True)
                page.locator("[data-drawer-close]").click()

            capture_section(page, ".bcc-lower", "13-executive-attention-and-watchlist.png")
            capture_section(page, ".bcc-actions-strip", "14-actions-and-decisions.png")

            mobile = context.new_page()
            mobile.set_viewport_size({"width": 390, "height": 844})
            mobile.on("pageerror", lambda error: errors.append(f"mobile: {error}"))
            mobile.goto(BASE_URL, wait_until="networkidle", timeout=120_000)
            mobile.wait_for_selector("[data-content]:visible", timeout=120_000)
            mobile.screenshot(path=str(OUTPUT / "15-mobile-full-page.png"), full_page=True)
            mobile.close()

            overflow = page.evaluate(
                "() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1"
            )
            if overflow:
                raise AssertionError("Desktop page has horizontal overflow.")
            if errors:
                raise AssertionError(f"Browser errors: {errors}")
            browser.close()
    finally:
        server.shutdown()
        server.server_close()

    print(f"Captured 15 real-data screenshots in {OUTPUT}")


if __name__ == "__main__":
    main()
