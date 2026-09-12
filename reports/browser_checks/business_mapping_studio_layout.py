"""Responsive browser validation for Business Mapping Studio."""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from wsgiref.simple_server import make_server

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Mining360IA.settings")

import django

django.setup()

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.handlers import StaticFilesHandler
from django.core.wsgi import get_wsgi_application
from django.test import Client
from playwright.sync_api import sync_playwright


def session_cookie():
    user = get_user_model().objects.filter(is_superuser=True, is_active=True).first()
    if not user:
        raise RuntimeError("An active superuser is required.")
    client = Client()
    client.force_login(user)
    return client.cookies[settings.SESSION_COOKIE_NAME].value


def main():
    output = Path(".artifacts/business-mapping-studio")
    output.mkdir(parents=True, exist_ok=True)
    cookie = session_cookie()
    server = make_server("127.0.0.1", 8121, StaticFilesHandler(get_wsgi_application()))
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        run_browser_checks(cookie, output)
    finally:
        server.shutdown()
        server.server_close()


def run_browser_checks(cookie, output):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
        context = browser.new_context()
        context.add_cookies([{"name": settings.SESSION_COOKIE_NAME, "value": cookie, "domain": "127.0.0.1", "path": "/", "httpOnly": True, "sameSite": "Lax"}])
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" and "Failed to load resource" not in message.text else None)
        sync_id = "00000000-0000-0000-0000-000000000001"
        page.route("**/api/business-mapping/synchronization/", lambda route, request: route.fulfill(
            status=202 if request.method == "POST" else 200,
            json={
                "ok": True,
                "run": ({
                    "id": sync_id,
                    "status": "Queued",
                    "progress_percent": 10,
                    "stage": "Waiting for the synchronization worker",
                    "records_read": 0,
                    "records_created": 0,
                    "records_updated": 0,
                    "warning_count": 0,
                    "status_url": f"/api/business-mapping/synchronization/{sync_id}/",
                } if request.method == "POST" else None),
            },
        ))
        page.route(f"**/api/business-mapping/synchronization/{sync_id}/", lambda route: route.fulfill(json={
            "ok": True,
            "run": {
                "id": sync_id,
                "status": "Completed",
                "progress_percent": 100,
                "stage": "Source synchronization completed",
                "records_read": 1738,
                "records_created": 12,
                "records_updated": 25,
                "warning_count": 0,
            },
        }))
        for width, height in ((1440, 900), (1024, 768), (390, 844)):
            page.set_viewport_size({"width": width, "height": height})
            page.goto("http://127.0.0.1:8121/data/business-mapping/", wait_until="networkidle")
            try:
                page.wait_for_selector("[data-bm-account-list] .bm-account-row", timeout=30_000)
            except Exception as exc:
                account_list_text = page.locator("[data-bm-account-list]").inner_text() if page.locator("[data-bm-account-list]").count() else "Account list missing"
                controls = page.evaluate("""
                    () => ({
                        search: Boolean(document.querySelector('[data-bm-account-search]')),
                        country: Boolean(document.querySelector('[data-bm-country-scope]')),
                        status: Boolean(document.querySelector('[data-bm-account-status]')),
                        sort: Boolean(document.querySelector('[data-bm-account-sort]')),
                        previous: Boolean(document.querySelector('[data-bm-previous]')),
                        next: Boolean(document.querySelector('[data-bm-next]')),
                        scripts: [...document.scripts].map(script => script.src).filter(Boolean),
                    })
                """)
                raise AssertionError(f"Account rows did not load: {account_list_text}; controls={controls}; browser errors={errors}") from exc
            result = page.evaluate("""
                () => ({
                    accountRows: document.querySelectorAll('.bm-account-row').length,
                    pageOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
                    metricOverflow: [...document.querySelectorAll('.bm-metrics > div')].some(node => node.scrollWidth > node.clientWidth + 2),
                    workspaceVisible: Boolean(document.querySelector('[data-bm-panel="workspace"]:not([hidden])')),
                    visibleTabs: [...document.querySelectorAll('[data-bm-tab]')].filter(node => node.offsetParent !== null).length,
                    bodyClass: document.body.className,
                    navDisplay: getComputedStyle(document.querySelector('.nav-links')).display,
                    navHeight: document.querySelector('.app-nav').getBoundingClientRect().height,
                })
            """)
            if result["accountRows"] < 1 or result["pageOverflow"] or result["metricOverflow"] or not result["workspaceVisible"] or result["visibleTabs"] < 5:
                raise AssertionError(f"Layout failed at {width}x{height}: {result}")
            page.screenshot(path=str(output / f"business-mapping-{width}x{height}.png"), full_page=True)
            print(f"PASS {width}x{height}: {result}")

        page.set_viewport_size({"width": 1440, "height": 900})
        page.goto("http://127.0.0.1:8121/data/business-mapping/", wait_until="networkidle")
        revenue_controls_are_governed = page.evaluate("""
            () => {
                const revenue = document.querySelector('.bm-revenue-scope');
                const period = document.querySelector('[data-bm-period-select]');
                const labels = [...document.querySelectorAll('.bm-revenue-scope [data-bm-revenue-filter] > span')]
                    .map(node => node.textContent.trim());
                return Boolean(
                    revenue
                    && period
                    && period.closest('.bm-header')
                    && (period.compareDocumentPosition(revenue) & Node.DOCUMENT_POSITION_FOLLOWING)
                    && JSON.stringify(labels) === JSON.stringify(['Total', 'Machine', 'Parts', 'Service', 'Rental'])
                );
            }
        """)
        if not revenue_controls_are_governed:
            raise AssertionError("Revenue period or ordered Total/Machine/Parts/Service/Rental cards are not positioned correctly.")
        period_select = page.locator("[data-bm-period-select]")
        period_values = period_select.locator("option").evaluate_all("options => options.map(option => option.value)")
        if period_values != ["ytd", "2025", "2024", "2023", "all"]:
            raise AssertionError(f"Historical Revenue period options are incomplete: {period_values}")
        with page.expect_response(lambda response: "/api/business-mapping/overview/" in response.url and "period=2024" in response.url) as period_overview:
            with page.expect_response(lambda response: "/api/business-mapping/accounts/" in response.url and "period=2024" in response.url) as period_accounts:
                period_select.select_option("2024")
        if not period_overview.value.ok or not period_accounts.value.ok or "2024" not in page.locator('[data-bm-context="revenue"]').inner_text():
            raise AssertionError("The 2024 Revenue period did not refresh the complete Mapping page.")
        with page.expect_response(lambda response: "/api/business-mapping/accounts/" in response.url and "period=all" in response.url):
            period_select.select_option("all")
        if "All available periods" not in page.locator('[data-bm-context="revenue"]').inner_text():
            raise AssertionError("The All periods Revenue view was not retained in the global context.")
        with page.expect_response(lambda response: "/api/business-mapping/accounts/" in response.url and "period=ytd" in response.url):
            period_select.select_option("ytd")
        with page.expect_response(lambda response: "/api/business-mapping/accounts/" in response.url and "search=61-12229" in response.url):
            page.locator("[data-bm-account-search]").fill("61-12229")
        page.wait_for_selector("[data-bm-account-list] .bm-account-row")
        account_identity = page.locator("[data-bm-account-list] .bm-account-row .bm-account-identity").first.inner_text()
        if "61-12229" not in account_identity or "CIC MN50" not in account_identity or "Burkina Faso" not in account_identity:
            raise AssertionError(f"Account identity is missing code, CIC or country: {account_identity}")
        source_toggle = page.locator("[data-bm-account-list] [data-source-toggle]").first
        source_toggle.click()
        source_records = page.locator("[data-bm-account-list] .bm-source-records:not([hidden]) .bm-source-record")
        if source_toggle.get_attribute("aria-expanded") != "true" or source_records.count() < 2:
            raise AssertionError("Canonical Account source records did not expand correctly.")
        expanded_text = page.locator("[data-bm-account-list] .bm-source-records:not([hidden])").inner_text()
        if "61-12229" not in expanded_text or "23-12229" not in expanded_text:
            raise AssertionError(f"Canonical Account source-record list is incomplete: {expanded_text}")
        country_filter = page.locator("[data-bm-country-scope]")
        if country_filter.input_value() != "" or country_filter.locator('option[value="BF"]').inner_text() != "Burkina Faso":
            raise AssertionError("Country filter does not default to Group or expose Burkina Faso.")
        operating_options = country_filter.locator("option").evaluate_all("options => options.map(option => option.value)")
        expected_operating_options = ["", "SN", "CI", "GN", "ML", "BF", "NE", "BJ", "TG", "MR", "FR", "CM", "GW", "MU"]
        if operating_options != expected_operating_options or "CA" in operating_options or "US" in operating_options:
            raise AssertionError(f"Global filter is not limited to governed Neemba operating countries: {operating_options}")
        with page.expect_response(lambda response: "/api/business-mapping/overview/" in response.url and "country=BF" in response.url) as overview_country_response:
            with page.expect_response(lambda response: "/api/business-mapping/accounts/" in response.url and "country=BF" in response.url) as country_response:
                country_filter.select_option("BF")
        if not country_response.value.ok or not overview_country_response.value.ok:
            raise AssertionError("Burkina Faso global scope did not refresh the page successfully.")
        with page.expect_response(lambda response: "/api/business-mapping/accounts/" in response.url and "country=&" in response.url):
            country_filter.select_option("")
        with page.expect_response(lambda response: "/api/business-mapping/accounts/" in response.url and "search=" in response.url):
            page.locator("[data-bm-account-search]").fill("")
        if page.locator("[data-assign-country], [data-bm-assign-country-dialog]").count() != 0:
            raise AssertionError("The removed direct Country Account assignment workflow is still visible.")
        if page.locator("[data-bm-account-sort]").input_value() != "revenue_desc":
            raise AssertionError("Revenue descending sort is not the default.")
        with page.expect_response(lambda response: "/api/business-mapping/overview/" in response.url and "lob=PARTS" in response.url) as overview_response:
            with page.expect_response(lambda response: "/api/business-mapping/accounts/" in response.url and "lob=PARTS" in response.url) as accounts_response:
                page.locator('[data-bm-revenue-filter="PARTS"]').click()
        if not overview_response.value.ok or not accounts_response.value.ok:
            raise AssertionError("Parts revenue filter did not execute successfully.")
        if page.locator('[data-bm-revenue-filter="PARTS"]').get_attribute("aria-pressed") != "true":
            raise AssertionError("Parts revenue filter did not retain its selected state.")
        if page.locator("[data-bm-country-accounts], [data-bm-country-account-filter], [data-bm-country-account-dialog]").count() != 0:
            raise AssertionError("The retired Country Account workflow is still visible.")
        with page.expect_response(lambda response: "/api/business-mapping/key-accounts/" in response.url) as key_accounts_response:
            page.locator("[data-bm-key-accounts]").click()
        if not key_accounts_response.value.ok or not page.locator("[data-bm-key-account-dialog]").is_visible():
            raise AssertionError("Key Account management did not open or load.")
        if not page.locator("[data-bm-key-name]").is_visible() or not page.locator("[data-bm-key-search]").is_visible():
            raise AssertionError("Key Account creation or Canonical Account search is unavailable.")
        if page.locator("[data-bm-key-sort]").input_value() != "revenue_desc":
            raise AssertionError("Key Accounts are not sorted by highest Revenue by default.")
        unassigned_group = page.locator('[data-key-account-id=""]')
        if not unassigned_group.is_visible() or "Unassigned Canonical Accounts" not in page.locator("[data-bm-key-detail]").inner_text():
            raise AssertionError("The Key Account selection cannot be cleared to review unassigned Canonical Accounts.")
        page.locator("[data-bm-key-close]").click()
        if page.locator("[data-bm-key-account-filter]").locator('option[value="unassigned"]').count() != 1:
            raise AssertionError("The one-click Key Account filter does not expose unassigned Accounts.")
        page.locator("[data-bm-sync]").click()
        page.wait_for_selector('[data-bm-sync-progress][data-status="Completed"]', timeout=10_000)
        if page.locator("[data-bm-sync-percent]").inner_text() != "100%" or "1,738 read" not in page.locator("[data-bm-sync-counts]").inner_text():
            raise AssertionError("Synchronization progress did not reach its completed state.")
        with page.expect_response(lambda response: "/api/business-mapping/accounts/" in response.url and "status=Unmapped" in response.url):
            page.locator("[data-bm-account-status]").select_option("Unmapped")
        page.locator(".bm-account-row").first.click()
        page.wait_for_selector("[data-bm-selected-summary] strong")
        if not page.locator("[data-bm-alias-panel]").is_visible() or not page.locator("[data-bm-alias-input]").is_visible():
            raise AssertionError("Canonical Account alias management is unavailable.")
        if not page.locator("[data-bm-operating-country-panel]").is_visible():
            raise AssertionError("Canonical Account operating-country assignment is unavailable.")
        operating_assignment_options = page.locator("[data-bm-operating-country-input] option").evaluate_all("options => options.map(option => option.value)")
        if "MR" not in operating_assignment_options or "GN" not in operating_assignment_options:
            raise AssertionError(f"Operating-country assignment options are incomplete: {operating_assignment_options}")
        if not page.locator("[data-bm-manual-site]").is_visible():
            raise AssertionError("MineSite selection did not become available.")
        removed_fields = page.locator("[data-bm-role], [data-bm-valid-from], [data-bm-primary], [data-bm-allocation-required], [data-bm-comment]")
        if removed_fields.count() != 0:
            raise AssertionError("The simplified Account to MineSite form still exposes removed fields.")
        page.locator('[data-bm-decision-form] button[type="submit"]').click()
        if not page.locator("[data-bm-form-error]").is_visible():
            raise AssertionError("Incomplete validation did not display a controlled field error.")
        page.locator("[data-bm-minesite-search]").fill("Fekola")
        page.wait_for_selector("[data-bm-minesite-results] [data-site-id]", timeout=10_000)
        page.locator("[data-bm-minesite-results] [data-site-id]").first.click()
        page.locator('[data-bm-decision-form] button[type="submit"]').click()
        if not page.locator("[data-bm-validation-dialog]").is_visible():
            diagnostics = page.evaluate("""
                () => ({
                    formError: document.querySelector('[data-bm-form-error]')?.textContent,
                    formErrorHidden: document.querySelector('[data-bm-form-error]')?.hidden,
                    selectedSite: document.querySelector('[data-bm-impact]')?.innerText,
                    dialogOpen: document.querySelector('[data-bm-validation-dialog]')?.open,
                })
            """)
            raise AssertionError(f"Complete validation did not open the confirmation dialog: {diagnostics}; errors={errors}")
        if "Fekola" not in page.locator("[data-bm-validation-review]").inner_text():
            raise AssertionError("Validation confirmation does not contain the selected MineSite.")
        page.locator("[data-bm-validation-dialog] [data-bm-close]").first.click()
        page.locator('[data-bm-tab="conflicts"]').click()
        page.wait_for_timeout(500)
        if not page.locator('[data-bm-panel="conflicts"]').is_visible():
            raise AssertionError("Conflicts panel did not open.")
        if errors:
            raise AssertionError(f"Browser errors: {errors}")
        print("PASS Global country, synchronization progress, revenue filter/sort, validation feedback/dialog, MineSite control and conflicts tab")
        browser.close()


if __name__ == "__main__":
    main()
