"""Real-data interaction and visual regression checks for Command Center V2."""
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
    "ENABLE_BUSINESS_COMMAND_CENTER_V2",
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


OUTPUT = PROJECT_ROOT / "docs" / "screenshots" / "business-command-center-v2-2026-09-14"
BASE_URL = "http://127.0.0.1:8128/business-review/command-center/"


def session_cookie() -> str:
    user_model = get_user_model()
    user = user_model.objects.filter(username="papa.diagne@neemba.com", is_active=True).first()
    user = user or user_model.objects.filter(is_superuser=True, is_active=True).first()
    if user is None:
        raise RuntimeError("No authorized active user is available.")
    client = Client()
    client.force_login(user)
    return client.cookies[settings.SESSION_COOKIE_NAME].value


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    cookie_value = session_cookie()
    server = make_server("127.0.0.1", 8128, StaticFilesHandler(get_wsgi_application()))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    errors = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            )
            context = browser.new_context()
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
            api_urls = []
            page.on("response", lambda response: api_urls.append(response.url) if "/api/business-review/" in response.url else None)

            for width, height, name in (
                (1920, 1080, "desktop-wide"),
                (1440, 900, "desktop"),
                (1366, 768, "laptop"),
                (1280, 800, "laptop-scaled"),
                (768, 1024, "tablet"),
                (390, 844, "mobile"),
            ):
                api_urls.clear()
                page.set_viewport_size({"width": width, "height": height})
                page.goto(BASE_URL, wait_until="networkidle", timeout=120_000)
                page.wait_for_selector('[data-workspace="executive"].active')
                checks = page.evaluate("""() => ({
                    overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
                    height: document.documentElement.scrollHeight,
                    viewport: innerHeight,
                    hero: document.querySelector('[data-hero-value]')?.textContent,
                    cards: document.querySelectorAll('[data-line]').length,
                    machineRows: document.querySelectorAll('[data-machine-body] tr').length,
                    partsRows: document.querySelectorAll('[data-parts-body] tr').length,
                    sidebarOverlap: (() => {
                        const nav = document.querySelector('.app-nav');
                        const shell = document.querySelector('.bcc-shell');
                        return innerWidth > 720 && nav && shell
                            ? nav.getBoundingClientRect().right > shell.getBoundingClientRect().left + 1
                            : false;
                    })(),
                })""")
                initial_business_apis = [url for url in api_urls if "/api/business-review/" in url]
                if checks["overflow"] or checks["sidebarOverlap"] or checks["cards"] != 4 or checks["machineRows"] or checks["partsRows"]:
                    raise AssertionError(f"{name}: {checks}")
                if len(initial_business_apis) != 1 or "/bootstrap/" not in initial_business_apis[0]:
                    raise AssertionError(f"{name}: initial APIs {initial_business_apis}")
                if name in {"desktop-wide", "desktop"} and checks["height"] / checks["viewport"] > 1.5:
                    raise AssertionError(f"{name}: executive overview is too tall: {checks}")
                page.screenshot(path=str(OUTPUT / f"01-executive-{name}.png"), full_page=True)

            page.set_viewport_size({"width": 1440, "height": 900})
            page.goto(BASE_URL, wait_until="networkidle", timeout=120_000)
            if page.locator('[data-division-toggle]').is_checked():
                raise AssertionError("All Divisions must not replace the default Mining scope.")
            page.locator('[data-division-toggle]').check()
            page.wait_for_selector('[data-update-loader]', state="hidden", timeout=120_000)
            if "division_scope=all_divisions" not in page.url:
                raise AssertionError(f"All Divisions was not persisted in the URL: {page.url}")
            if "ALL DIVISIONS" not in page.locator('[data-hero-label]').inner_text().upper():
                raise AssertionError("The Revenue hero does not identify the All Divisions scope.")
            page.locator('[data-workspace-tab="operations"]').first.click()
            if not page.locator('[data-sales-scope-warning]').is_visible():
                raise AssertionError("Mining-only operational detail limitation is not disclosed.")
            page.locator('[data-workspace-tab="executive"]').first.click()
            page.locator('[data-division-toggle]').uncheck()
            page.wait_for_selector('[data-update-loader]', state="hidden", timeout=120_000)
            if "division_scope=mining" not in page.url:
                raise AssertionError(f"Mining scope was not restored in the URL: {page.url}")
            page.locator('[data-filter="period"]').select_option("custom")
            if not page.locator('[data-custom-date]').first.is_visible():
                raise AssertionError("Custom Revenue date range controls are not visible.")
            latest_revenue_date = page.locator('[data-filter="end_date"]').get_attribute("max")
            if not latest_revenue_date:
                raise AssertionError("Custom Revenue dates are not capped by the latest available Revenue date.")
            page.locator('[data-filter="end_date"]').fill("2099-01-01")
            page.locator('[data-filter="end_date"]').press("Tab")
            if page.locator('[data-filter="end_date"]').input_value() != latest_revenue_date:
                raise AssertionError("A future custom End Date was not clamped to Revenue through date.")
            page.locator('[data-filter="start_date"]').fill("2024-01-01")
            page.locator('[data-filter="end_date"]').fill("2024-12-31")
            page.locator('[data-filter="end_date"]').press("Tab")
            page.wait_for_selector('[data-update-loader]', state="hidden", timeout=120_000)
            if "period=custom" not in page.url or "start_date=2024-01-01" not in page.url or "end_date=2024-12-31" not in page.url:
                raise AssertionError(f"Custom Revenue date range was not persisted in the URL: {page.url}")
            page.locator('[data-reset]').click()
            page.wait_for_selector('[data-update-loader]', state="hidden", timeout=120_000)
            if page.locator('[data-filter="period"]').input_value() != "ytd":
                raise AssertionError("Reset did not restore the YTD Revenue period.")
            if page.locator('[data-combobox="customers"]').count():
                raise AssertionError("Customer Country Group must not appear in Command Center filters.")
            page.locator('[data-combobox="key_accounts"] [data-combobox-toggle]').click()
            page.wait_for_selector('[data-search-results="key_accounts"] [data-search-id]')
            if page.locator('[data-search-results="key_accounts"] [data-search-id]').count() < 2:
                raise AssertionError("Key Account dropdown did not load authorized values on open.")
            page.locator('[data-entity-search="key_accounts"]').fill("COR")
            page.wait_for_timeout(400)
            if "COR" not in page.locator('[data-search-results="key_accounts"]').inner_text().upper():
                raise AssertionError("Key Account dropdown search did not return the expected value.")
            page.locator('[data-combobox="key_accounts"] [data-combobox-toggle]').click()
            if page.locator('[data-trend-total]').inner_text().strip() in {"", "--"}:
                raise AssertionError("YTD Revenue Trend total is not rendered.")
            page.locator('[data-brief-tab="yesterday"]').click()
            page.screenshot(path=str(OUTPUT / "06-since-yesterday.png"), full_page=True)
            page.locator('[data-trend-mode="mtd"]').click()
            if page.locator('[data-trend-total]').inner_text().strip() in {"", "--"}:
                raise AssertionError("MTD Revenue Trend total is not rendered.")
            page.screenshot(path=str(OUTPUT / "07-revenue-trend-mtd.png"), full_page=True)
            if page.locator('[data-trend-mode="daily"]').count():
                raise AssertionError("Daily must not be exposed in Revenue Trend.")
            page.screenshot(path=str(OUTPUT / "08-revenue-trend-ytd-mtd.png"), full_page=True)
            page.locator('[data-trend-fullscreen]').click()
            page.wait_for_function("document.fullscreenElement?.matches('[data-export-surface=\"trend\"]')")
            page.evaluate("document.exitFullscreen()")
            page.locator('[data-workspace-tab="turnover"]').first.click()
            page.wait_for_selector('[data-turnover-matrix-body] tr')
            turnover = page.evaluate("""() => ({
                kpis: document.querySelectorAll('[data-turnover-line]').length,
                removedCountryChart: document.querySelectorAll('[data-country-bars]').length,
                matrixRows: document.querySelectorAll('[data-turnover-matrix-body] tr').length,
                overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
            })""")
            if turnover["kpis"] != 5 or turnover["removedCountryChart"] or turnover["matrixRows"] != 4 or turnover["overflow"]:
                raise AssertionError(f"Mining Turnover rendering failed: {turnover}")
            page.screenshot(path=str(OUTPUT / "09-mining-turnover.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            if page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth + 1"):
                raise AssertionError("Mining Turnover has horizontal page overflow on mobile.")
            page.screenshot(path=str(OUTPUT / "09b-mining-turnover-mobile.png"), full_page=True)
            page.set_viewport_size({"width": 1440, "height": 900})
            if page.locator('[data-workspace-tab="explore"]').count():
                raise AssertionError("The retired Explore workspace is visible again.")

            page.locator('[data-workspace-tab="operations"]').first.click()
            page.wait_for_selector('[data-machine-table-wrap]:visible', timeout=120_000)
            if page.locator('[data-machine-family-card]').count() != 11:
                raise AssertionError("The 11 governed Machine product-group filters are not rendered.")
            if page.locator('[data-machine-family-card] img').count() != 9:
                raise AssertionError("The exact-name Machine product-group image set is incomplete.")
            page.wait_for_function("""() => [...document.querySelectorAll('[data-machine-family-card] img')]
                .every(image => image.complete && image.naturalWidth > 0)""", timeout=30_000)
            if not page.locator('[data-machine-family-card] img').evaluate_all("images => images.every(image => image.complete && image.naturalWidth > 0)"):
                raise AssertionError("One or more Machine family images failed to load.")
            if not page.locator('[data-machine-family-card="OHT"] img').get_attribute("src").endswith("machine-family-oht.jpeg"):
                raise AssertionError("OHT is not using the governed Off Highway Trucks image.")
            card_tops = page.locator('[data-machine-family-card]').evaluate_all(
                "cards => cards.slice(0, 5).map(card => Math.round(card.getBoundingClientRect().top))"
            )
            if len(set(card_tops[:4])) != 1 or card_tops[4] <= card_tops[0]:
                raise AssertionError(f"Machine product groups are not arranged four per row: {card_tops}")
            page.locator('[data-machine-family-card="HMS"]').click()
            page.wait_for_timeout(500)
            if page.locator('[data-machine-filter="family"]').input_value() != "HMS" or page.locator('[data-machine-family-card="HMS"]').get_attribute("aria-pressed") != "true":
                raise AssertionError("The HMS visual filter did not synchronize with the Machine family selector.")
            page.locator('[data-machine-family-card="HMS"]').click()
            if page.locator('[data-machine-body]').inner_text().casefold().find("portfolio rounding reconciliation") >= 0:
                raise AssertionError("Technical reconciliation row is visible as a Customer.")
            page.screenshot(path=str(OUTPUT / "13-machine-sales.png"), full_page=True)
            page.locator('[data-operation-tab="parts"]').click()
            page.wait_for_selector('[data-parts-table-wrap]:visible', timeout=120_000)
            if "matched subset only" not in page.locator('[data-operation-view="parts"]').inner_text().casefold():
                raise AssertionError("Parts coverage limitation is not prominent.")
            page.screenshot(path=str(OUTPUT / "14-parts-classification.png"), full_page=True)

            page.locator('[data-workspace-tab="actions"]').first.click()
            page.screenshot(path=str(OUTPUT / "15-actions-and-watchlist.png"), full_page=True)
            page.locator('[data-workspace-tab="executive"]').first.click()
            page.locator('[data-confidence-open]').first.click()
            page.wait_for_selector('[data-drawer]:visible')
            page.screenshot(path=str(OUTPUT / "16-data-confidence-drawer.png"), full_page=True)
            page.locator('[data-drawer-close]').click()
            page.set_viewport_size({"width": 1600, "height": 900})
            page.locator('[data-presentation]').click()
            page.wait_for_timeout(500)
            page.screenshot(path=str(OUTPUT / "17-presentation-mode.png"), full_page=True)

            if errors:
                raise AssertionError(f"Browser errors: {errors}")
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    print(f"PASS: 18 V2 real-data screenshots saved to {OUTPUT}")


if __name__ == "__main__":
    main()
