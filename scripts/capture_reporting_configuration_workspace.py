"""Capture authenticated responsive snapshots of Reporting Configuration."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Mining360IA.settings")

import django

django.setup()

from django.contrib.auth import get_user_model
from django.test import Client
from playwright.sync_api import sync_playwright


VIEWPORTS = {
    "desktop-1920x1080": (1920, 1080),
    "desktop-1440x900": (1440, 900),
    "laptop-1366x768": (1366, 768),
    "tablet-1024x768": (1024, 768),
    "mobile-390x844": (390, 844),
}

SYSTEM_BROWSERS = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
)


def main():
    user = get_user_model().objects.filter(is_active=True, is_superuser=True).order_by("id").first()
    if user is None:
        raise RuntimeError("An active superuser is required for authenticated screenshots.")

    client = Client()
    client.force_login(user)
    session_cookie = client.cookies["sessionid"].value
    output = Path("artifacts/reporting-configuration")
    output.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        executable = next((path for path in SYSTEM_BROWSERS if path.exists()), None)
        if executable is None:
            raise RuntimeError("Chrome or Edge is required for responsive screenshots.")
        browser = playwright.chromium.launch(headless=True, executable_path=str(executable))
        context = browser.new_context(base_url="http://127.0.0.1:8001")
        context.add_cookies([{
            "name": "sessionid",
            "value": session_cookie,
            "domain": "127.0.0.1",
            "path": "/",
            "httpOnly": True,
            "sameSite": "Lax",
        }])
        page = context.new_page()
        errors = []
        console_errors = []
        api_responses = []
        page.on("pageerror", lambda error: errors.append(error.stack or str(error)))
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        page.on(
            "response",
            lambda response: api_responses.append((response.status, response.url))
            if "/api/reporting/configurations" in response.url
            else None,
        )
        page.goto("/config/reporting/", wait_until="networkidle", timeout=60_000)
        page.wait_for_selector("[data-report-config-workspace]", timeout=30_000)
        try:
            page.wait_for_selector(".selected-report-shell:not([hidden])", timeout=60_000)
        except Exception:
            page.screenshot(path=str(output / "load-failure.png"), full_page=True)
            print("API responses:", api_responses)
            print("Page errors:", errors)
            print("Console errors:", console_errors)
            raise

        results = []
        for name, (width, height) in VIEWPORTS.items():
            page.set_viewport_size({"width": width, "height": height})
            page.wait_for_timeout(350)
            overflow = page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
            layout = page.evaluate("""({
                bodyClass: document.body.className,
                mainLeft: document.querySelector('[data-report-config-workspace]').getBoundingClientRect().left,
                mainHeight: document.querySelector('[data-report-config-workspace]').getBoundingClientRect().height,
                documentHeight: document.documentElement.scrollHeight,
                navWidth: document.querySelector('.app-nav').getBoundingClientRect().width,
                listClientHeight: document.querySelector('[data-report-list]').clientHeight,
                listScrollHeight: document.querySelector('[data-report-list]').scrollHeight,
                editor: (() => { const element=document.querySelector('.report-config-editor'); const rect=element.getBoundingClientRect(); return {top:rect.top,bottom:rect.bottom,height:rect.height}; })(),
                shell: (() => { const element=document.querySelector('.selected-report-shell'); const rect=element.getBoundingClientRect(); return {top:rect.top,bottom:rect.bottom,height:rect.height,clientHeight:element.clientHeight,scrollHeight:element.scrollHeight}; })(),
                form: (() => { const element=document.querySelector('[data-config-form]'); const rect=element.getBoundingClientRect(); return {top:rect.top,bottom:rect.bottom,height:rect.height,clientHeight:element.clientHeight,scrollHeight:element.scrollHeight}; })(),
                actionBar: (() => { const element=document.querySelector('.configuration-action-bar'); const rect=element.getBoundingClientRect(); return {top:rect.top,bottom:rect.bottom,height:rect.height}; })()
            })""")
            screenshot = output / f"{name}.png"
            page.screenshot(path=str(screenshot), full_page=False)
            results.append((name, overflow, screenshot, layout))

        page.set_viewport_size({"width": 1440, "height": 900})
        page.wait_for_timeout(250)
        for tab in ("general", "visual", "catalog", "launch", "navigation", "troubleshooting", "parameters", "tests", "audit"):
            page.locator(f'[data-tab="{tab}"]').click()
            panel = page.locator(f'[data-panel="{tab}"]')
            panel.wait_for(state="visible")
            if not panel.inner_text().strip():
                raise RuntimeError(f"The {tab} tab has no visible content.")
            page.screenshot(path=str(output / f"tab-{tab}-1440x900.png"), full_page=False)

        page.locator('[data-tab="visual"]').click()
        for mode in ("desktop", "laptop", "mobile", "list"):
            page.locator(f'[data-preview-mode="{mode}"]').click()
            preview = page.locator("[data-card-preview]")
            if not preview.is_visible():
                raise RuntimeError(f"The {mode} report-card preview is not visible.")
            page.screenshot(path=str(output / f"visual-preview-{mode}-1440x900.png"), full_page=False)

        page.locator('[data-tab="troubleshooting"]').click()
        scroll_result = page.locator("[data-config-form]").evaluate("""element => {
            const before = element.scrollTop;
            element.scrollTop = element.scrollHeight;
            return {
                clientHeight: element.clientHeight,
                scrollHeight: element.scrollHeight,
                before,
                after: element.scrollTop
            };
        }""")
        if scroll_result["scrollHeight"] > scroll_result["clientHeight"] and scroll_result["after"] <= 0:
            raise RuntimeError(f"The report configuration editor cannot scroll: {scroll_result}")

        page.locator('[data-tab="general"]').click()
        page.locator(".report-config-advanced summary").click()
        technical_values = page.locator(".technical-details dd").all_inner_texts()
        if len(technical_values) < 5 or not any(value.strip() for value in technical_values):
            raise RuntimeError(f"Advanced technical details are not populated: {technical_values}")
        advanced_scroll = page.locator("[data-config-form]").evaluate("""element => {
            element.scrollTop = element.scrollHeight;
            return {clientHeight: element.clientHeight, scrollHeight: element.scrollHeight, scrollTop: element.scrollTop};
        }""")
        if advanced_scroll["scrollHeight"] > advanced_scroll["clientHeight"] and advanced_scroll["scrollTop"] <= 0:
            raise RuntimeError(f"Advanced technical details cannot be scrolled into view: {advanced_scroll}")
        page.screenshot(path=str(output / "advanced-technical-details-1440x900.png"), full_page=False)

        page.locator('[data-tab="parameters"]').click()
        page.locator("[data-parameter-add]").click()
        if page.locator("[data-parameter-drawer]").get_attribute("aria-hidden") != "false":
            raise RuntimeError("The context-parameter drawer did not open.")
        page.locator("[data-parameter-close]").first.click()

        browser.close()

    for name, overflow, screenshot, layout in results:
        print(f"{name}: horizontal_overflow={overflow} screenshot={screenshot} layout={layout}")
    if errors:
        raise RuntimeError("Browser errors: " + " | ".join(errors))
    if any(overflow for _, overflow, _, _ in results):
        raise RuntimeError("Horizontal overflow detected in one or more viewports.")


if __name__ == "__main__":
    main()
