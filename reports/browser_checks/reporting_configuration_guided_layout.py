"""Responsive and interaction checks for the guided Reporting Configuration workspace."""

from __future__ import annotations

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


BASE_URL = "https://mining360-dev.neemba.local/config/reporting/"
VIEWPORTS = ((1920, 1080), (1600, 900), (1440, 900), (1366, 768), (1280, 800), (1024, 768), (768, 1024), (390, 844))


def authenticated_session_cookie() -> str:
    user = get_user_model().objects.filter(is_superuser=True, is_active=True).first()
    if not user:
        raise RuntimeError("An active superuser is required for the browser check.")
    client = Client()
    client.force_login(user)
    return client.cookies[settings.SESSION_COOKIE_NAME].value


def wait_for_workspace(page) -> None:
    page.wait_for_selector("[data-report-config-workspace]", state="visible", timeout=60_000)
    page.wait_for_selector("[data-report-id]", state="attached", timeout=60_000)
    page.wait_for_selector("[data-editor-content]:not([hidden])", state="visible", timeout=60_000)


def assert_layout(page, width: int) -> None:
    result = page.evaluate("""
        () => ({
            pageOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
            workspaceOverflow: document.querySelector('.report-config-workspace').scrollWidth > document.querySelector('.report-config-workspace').clientWidth + 1,
            mainSummaryCount: document.querySelectorAll('.report-config-summary > [data-summary-filter]').length,
            primaryAreaCount: document.querySelectorAll('[data-area]').length,
            originalPanelCount: document.querySelectorAll('[data-panel]').length,
            visibleHeaderActions: [...document.querySelectorAll('.selected-report-header__actions > *')].filter(node => !node.hidden).length,
            clippedActionBar: document.querySelector('.configuration-action-bar').getBoundingClientRect().right > innerWidth + 1,
        })
    """)
    assert not result["pageOverflow"], (width, result)
    assert not result["workspaceOverflow"], (width, result)
    assert result["mainSummaryCount"] == 4, result
    assert result["primaryAreaCount"] == 5, result
    assert result["originalPanelCount"] == 10, result
    assert result["visibleHeaderActions"] == 3, result
    assert not result["clippedActionBar"], result


def main() -> None:
    output_dir = PROJECT_ROOT / ".artifacts" / "reporting-configuration-guided"
    output_dir.mkdir(parents=True, exist_ok=True)
    cookie = authenticated_session_cookie()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
        context = browser.new_context(ignore_https_errors=True)
        context.add_cookies([{
            "name": settings.SESSION_COOKIE_NAME, "value": cookie,
            "domain": "mining360-dev.neemba.local", "path": "/",
            "secure": True, "httpOnly": True, "sameSite": "Lax",
        }])
        page = context.new_page()
        page.set_default_navigation_timeout(90_000)
        page.set_default_timeout(60_000)

        for width, height in VIEWPORTS:
            page.set_viewport_size({"width": width, "height": height})
            page.goto(BASE_URL, wait_until="domcontentloaded")
            wait_for_workspace(page)
            assert_layout(page, width)
            page.screenshot(path=str(output_dir / f"essentials-{width}x{height}.png"), animations="disabled")

        page.set_viewport_size({"width": 1440, "height": 900})
        page.goto(BASE_URL, wait_until="domcontentloaded")
        wait_for_workspace(page)
        for area, file_name in (("appearance", "appearance.png"), ("open_navigate", "open-navigate.png"), ("help_ai", "help-ai.png")):
            page.locator(f'[data-area="{area}"]').click()
            page.screenshot(path=str(output_dir / file_name), animations="disabled")

        page.locator("[data-test-open]").click()
        page.wait_for_selector("[data-test-drawer].is-open")
        page.screenshot(path=str(output_dir / "test-drawer.png"), animations="disabled")
        page.locator("[data-test-close]").click()
        page.locator("[data-checklist-open]").click()
        page.wait_for_selector("[data-checklist-drawer].is-open")
        page.screenshot(path=str(output_dir / "configuration-checklist.png"), animations="disabled")
        page.locator("[data-checklist-close]").click()

        page.locator("[data-navigator-collapse]").click()
        assert page.locator("[data-report-config-workspace]").evaluate("node => node.classList.contains('navigator-collapsed')")
        page.screenshot(path=str(output_dir / "navigator-collapsed.png"), animations="disabled")

        page.goto(f"{BASE_URL}?tab=visual", wait_until="domcontentloaded")
        wait_for_workspace(page)
        assert page.locator('[data-area="appearance"]').get_attribute("aria-selected") == "true"
        assert not page.locator('[data-panel="visual"]').is_hidden()

        page.locator('[data-area="essentials"]').click()
        if page.locator("[data-report-config-workspace]").evaluate("node => node.classList.contains('navigator-collapsed')"):
            page.locator("[data-navigator-expand]").click()
        page.locator('[name="display_name"]').fill("Unsaved visual regression value")
        report_items = page.locator("[data-report-id]")
        if report_items.count() > 1:
            report_items.nth(1).click()
            page.wait_for_selector("[data-unsaved-dialog][open]")
            page.screenshot(path=str(output_dir / "unsaved-changes.png"), animations="disabled")
            page.locator('[data-unsaved-dialog] [value="discard"]').click()

        browser.close()
    print(f"PASS: guided Reporting Configuration screenshots written to {output_dir}")


if __name__ == "__main__":
    main()
