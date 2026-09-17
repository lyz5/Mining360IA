"""Visual and responsive smoke test for the Fuel Command Center mode."""

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


def authenticated_session_cookie() -> str:
    user = get_user_model().objects.filter(is_superuser=True, is_active=True).first()
    if not user:
        raise RuntimeError("An active superuser is required for the Fuel browser check.")
    client = Client()
    client.force_login(user)
    return client.cookies[settings.SESSION_COOKIE_NAME].value


def main() -> None:
    output_dir = Path(".artifacts/homepage-fuel")
    output_dir.mkdir(parents=True, exist_ok=True)
    cookie = authenticated_session_cookie()
    base_url = "https://mining360-dev.neemba.local/excellence-center/"

    with sync_playwright() as playwright:
        edge = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
        browser = playwright.chromium.launch(headless=True, executable_path=str(edge))
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
        browser_errors: list[str] = []
        page.on("pageerror", lambda error: browser_errors.append(str(error)))

        for width, height in ((1440, 900), (390, 844)):
            page.set_viewport_size({"width": width, "height": height})
            page.goto(f"{base_url}?metric=fuel", wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_selector("[data-metric-selector]", state="visible", timeout=30_000)
            page.wait_for_function(
                """
                () => document.querySelector('[data-updating]')?.hidden === true
                    && document.querySelector('[data-brand-loader]')?.hidden === true
                    && document.querySelector('[data-fuel-workspace]')?.hidden === false
                    && !['', '--'].includes(document.querySelector('[data-fuel-value]')?.textContent.trim())
                    && document.querySelectorAll('[data-fuel-chart] .fuel-point').length > 0
                    && document.querySelectorAll('[data-top-performers] .fuel-highlight-row').length > 0
                    && document.querySelectorAll('[data-bottom-performers] .fuel-highlight-row').length > 0
                    && document.querySelector('.performance-highlights')?.hidden === false
                """,
                timeout=90_000,
            )
            state = page.evaluate(
                """
                () => ({
                    value: document.querySelector('[data-fuel-value]')?.textContent.trim(),
                    title: document.querySelector('[data-center-title]')?.textContent.trim(),
                    points: document.querySelectorAll('[data-fuel-chart] .fuel-point').length,
                    lowestSignals: document.querySelectorAll('[data-top-performers] .fuel-highlight-row').length,
                    highestSignals: document.querySelectorAll('[data-bottom-performers] .fuel-highlight-row').length,
                    highlightsVisible: document.querySelector('.performance-highlights')?.hidden === false,
                    takeaway: document.querySelector('[data-key-takeaway]')?.textContent.trim(),
                    fuelVisible: !document.querySelector('[data-fuel-workspace]')?.hidden,
                    fleetHidden: Array.from(document.querySelectorAll('[data-fleet-workspace]'))
                        .filter(node => !node.matches('.performance-highlights'))
                        .every(node => node.hidden),
                    pageOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
                })
                """
            )
            if state["pageOverflow"] or not state["fuelVisible"] or not state["fleetHidden"]:
                raise AssertionError(f"{width}x{height}: invalid Fuel workspace state: {state}")
            if not state["value"] or state["value"] == "--" or state["points"] < 1:
                raise AssertionError(f"{width}x{height}: Fuel data did not render: {state}")
            page.screenshot(path=str(output_dir / f"fuel-{width}x{height}.png"), full_page=True)
            print(f"PASS Fuel {width}x{height}: {state['value']} L/h, {state['points']} distribution points")

            if width == 1440:
                site = page.locator('[data-filter="minesite"]')
                site.select_option("IAMGOLD Essakane")
                page.wait_for_function(
                    """
                    () => document.querySelector('[data-updating]')?.hidden === true
                        && document.querySelector('[data-fuel-value]')?.textContent.trim() === '73.9'
                        && document.querySelector('[data-fuel-scope]')?.textContent.trim() === 'IAMGOLD Essakane'
                    """,
                    timeout=90_000,
                )
                page.screenshot(path=str(output_dir / "fuel-essakane-1440x900.png"), full_page=True)
                print("PASS Fuel Essakane: 73.9 L/h")

        if browser_errors:
            raise AssertionError(f"Browser JavaScript errors: {browser_errors}")
        browser.close()


if __name__ == "__main__":
    main()
