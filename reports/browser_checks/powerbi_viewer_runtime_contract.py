"""Assert that ordinary viewer interactions reuse one Power BI instance."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Mining360IA.settings")

import django

django.setup()

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from playwright.sync_api import sync_playwright

from reports.models import PowerBIReport


BASE_URL = os.getenv("MINING360_BROWSER_BASE_URL", "http://127.0.0.1:8001")


def session_cookie() -> str:
    user = get_user_model().objects.filter(is_superuser=True, is_active=True).first()
    if not user:
        raise RuntimeError("An active superuser is required for the browser check.")
    client = Client()
    client.force_login(user)
    return client.cookies[settings.SESSION_COOKIE_NAME].value


MOCK_POWERBI = r"""
(() => {
    const metrics = window.__mockPowerBI = {
        embedCalls: 0, resetCalls: 0, filterCalls: 0, pageCalls: 0,
        fitCalls: 0, refreshCalls: 0, tokenCalls: 0, slicerScanCalls: 0, handlers: {}
    };
    const handlers = {};
    const activePage = {
        name: 'Overview', displayName: 'Overview', isActive: true,
        getSlicers: async () => { metrics.slicerScanCalls += 1; return []; },
        updateFilters: async () => { metrics.filterCalls += 1; },
        setActive: async () => { metrics.pageCalls += 1; }
    };
    const secondPage = {
        name: 'Details', displayName: 'Details', isActive: false,
        getSlicers: async () => [], updateFilters: async () => {},
        setActive: async () => { metrics.pageCalls += 1; activePage.isActive = false; secondPage.isActive = true; }
    };
    const report = {
        on(name, callback) { (handlers[name] ||= new Set()).add(callback); metrics.handlers[name] = handlers[name].size; },
        off(name, callback) { handlers[name]?.delete(callback); metrics.handlers[name] = handlers[name]?.size || 0; },
        getPages: async () => [activePage, secondPage],
        updateSettings: async () => { metrics.fitCalls += 1; },
        refresh: async () => { metrics.refreshCalls += 1; },
        removeFilters: async () => {},
        setAccessToken: async () => { metrics.tokenCalls += 1; }
    };
    window.powerbi = {
        embed() {
            metrics.embedCalls += 1;
            setTimeout(() => handlers.loaded?.forEach(callback => callback({detail: {}})), 20);
            setTimeout(() => handlers.rendered?.forEach(callback => callback({detail: {}})), 40);
            return report;
        },
        reset() { metrics.resetCalls += 1; }
    };
    window['powerbi-client'] = {models: {
        TokenType: {Aad: 0, Embed: 1}, Permissions: {Read: 1},
        DisplayOption: {FitToPage: 0, FitToWidth: 1, ActualSize: 2},
        LayoutType: {Custom: 1}, BackgroundType: {Transparent: 1, Default: 0},
        FilterType: {AdvancedFilter: 0, BasicFilter: 1},
        FiltersOperations: {RemoveAll: 0, Add: 1, ReplaceAll: 2},
        VisualContainerDisplayMode: {Visible: 0}
    }};
})();
"""


def viewer_payload(report_id: str, name: str) -> dict:
    return {
        "ok": True,
        "report": {"id": report_id, "display_name": name, "launch_mode": "generic_powerbi", "category_label": "Other"},
        "viewer": {
            "show_filter_bar": True,
            "available_periods": [
                {"code": "ytd", "label": "Year to Date"},
                {"code": "last_12_months", "label": "Last 12 Months"},
                {"code": "custom", "label": "Custom"},
            ],
            "default_period": "ytd", "auto_apply_presets": True,
            "custom_range_enabled": True, "show_page_navigation": True,
            "default_page": "", "default_fit_mode": "fit_to_page",
            "reset_behavior": "defaults", "help_text": "",
            "date_mapping": {"table": "Date", "column": "Date"},
        },
        "initial_context": {"period": "ytd", "start_date": "", "end_date": "", "page": "", "filters": [], "chips": []},
        "refresh_status": {"code": "neutral", "label": "Checking", "detail": ""},
        "permissions": {"allow_open_powerbi": False, "open_powerbi_url": "", "allow_focus": True, "allow_fullscreen": True},
    }


def main() -> None:
    configured = PowerBIReport.objects.filter(is_active=True, launch_mode="generic_powerbi").exclude(embed_url="").first()
    if not configured:
        raise RuntimeError("A generic report configuration is required.")
    report_id = str(configured.report_id)
    counters = {"viewerConfig": 0, "embedConfig": 0, "refreshStatus": 0, "embedUrls": []}
    cookie = session_cookie()
    host = urlsplit(BASE_URL).hostname or "127.0.0.1"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        )
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        context.add_cookies([{
            "name": settings.SESSION_COOKIE_NAME, "value": cookie,
            "domain": host, "path": "/", "httpOnly": True, "sameSite": "Lax",
        }])

        def route_request(route):
            url = route.request.url
            if "powerbi-client-" in url:
                route.fulfill(status=200, content_type="application/javascript", body=MOCK_POWERBI)
            elif "viewer-configuration" in url:
                counters["viewerConfig"] += 1
                route.fulfill(status=200, content_type="application/json", body=json.dumps(viewer_payload(report_id, configured.display_name)))
            elif "embed-config" in url:
                counters["embedConfig"] += 1
                if len(counters["embedUrls"]) < 10:
                    counters["embedUrls"].append(url)
                route.fulfill(status=200, content_type="application/json", body=json.dumps({
                    "ok": True,
                    "config": {"type": "report", "id": report_id, "embedUrl": "https://mock.invalid/report", "accessToken": "redacted", "tokenType": "Embed", "expiresAt": int(time.time()) + 3600},
                }))
            elif url.endswith("/refresh/"):
                counters["refreshStatus"] += 1
                route.fulfill(status=503, content_type="application/json", body='{"ok":false}')
            else:
                route.continue_()

        context.route("**/*", route_request)
        page = context.new_page()
        page.goto(BASE_URL + reverse("report-detail", args=[report_id]), wait_until="domcontentloaded")
        page.wait_for_function("() => Boolean(window.__mockPowerBI && document.querySelector('[data-loading-state]').hidden)")

        initial = page.evaluate("window.__mockPowerBI")
        page.locator('[data-period="custom"]').click()
        page.locator("[data-start-date]").fill("2026-02-01")
        page.locator("[data-end-date]").fill("2026-07-31")
        after_typing = page.evaluate("window.__mockPowerBI")
        apply_enabled = page.locator("[data-apply-filters]").is_enabled()
        page.locator("[data-apply-filters]").click()
        page.wait_for_timeout(500)
        page.locator('[data-fit-mode="actual_size"]').click()
        page.locator("[data-focus-toggle]").click()
        page.locator("[data-fullscreen-toggle]").click()
        page.wait_for_timeout(50)
        if page.evaluate("Boolean(document.fullscreenElement)"):
            page.evaluate("document.exitFullscreen()")
        page.locator('[data-page-name="Details"]').click()
        page.wait_for_timeout(50)
        final = page.evaluate("window.__mockPowerBI")

        assert counters["viewerConfig"] == 1, counters
        assert counters["embedConfig"] == 1, counters
        assert initial["embedCalls"] == 1 and initial["resetCalls"] == 0, initial
        assert after_typing["embedCalls"] == 1 and after_typing["filterCalls"] == initial["filterCalls"], after_typing
        assert final["embedCalls"] == 1 and final["resetCalls"] == 0, final
        assert apply_enabled, "Apply remained disabled after a valid custom range."
        assert final["filterCalls"] == 2, {
            "metrics": final,
            "filterStatus": page.locator("[data-filter-status]").inner_text(),
            "canvasStatus": page.locator("[data-canvas-state]").inner_text(),
        }
        assert final["slicerScanCalls"] == 0, final
        assert final["fitCalls"] == 1 and final["pageCalls"] == 1, final
        assert all(count == 1 for count in final["handlers"].values()), final["handlers"]

        recovery = page.evaluate("""
            async () => {
                const originalFetch = window.fetch;
                let calls = 0;
                window.fetch = async () => {
                    calls += 1;
                    if (calls === 1) return new Response(
                        JSON.stringify({ok: false, error: 'Busy'}),
                        {status: 429, headers: {'Content-Type': 'application/json', 'Retry-After': '0'}},
                    );
                    return new Response(
                        JSON.stringify({ok: true, config: {accessToken: 'redacted'}}),
                        {status: 200, headers: {'Content-Type': 'application/json'}},
                    );
                };
                try {
                    const runtime = new window.Mining360PowerBIEmbed(document.createElement('div'), {
                        embedConfigUrl: '/mock/__REPORT_ID__/embed-config/',
                        openRequestId: 'recovery-contract',
                    });
                    const config = await runtime.requestConfig('report');
                    return {calls, retryCount: runtime.metrics.retryCount, token: config.accessToken};
                } finally {
                    window.fetch = originalFetch;
                }
            }
        """)
        assert recovery == {"calls": 2, "retryCount": 1, "token": "redacted"}, recovery

        output = PROJECT_ROOT / ".artifacts" / "powerbi-viewer-stable-runtime"
        output.mkdir(parents=True, exist_ok=True)
        page.evaluate("document.body.classList.remove('viewer-focus')")
        responsive = {}
        for width, height in ((1920, 1080), (1440, 900), (1366, 768), (1024, 768), (768, 1024), (390, 844)):
            page.set_viewport_size({"width": width, "height": height})
            page.wait_for_timeout(100)
            layout = page.evaluate("""
                () => ({
                    horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
                    canvasMounted: Boolean(document.getElementById('powerbi-report')?.isConnected),
                    embedCalls: window.__mockPowerBI.embedCalls,
                    resetCalls: window.__mockPowerBI.resetCalls,
                })
            """)
            assert not layout["horizontalOverflow"] and layout["canvasMounted"], (width, height, layout)
            assert layout["embedCalls"] == 1 and layout["resetCalls"] == 0, (width, height, layout)
            responsive[f"{width}x{height}"] = layout
            page.screenshot(path=str(output / f"viewer-{width}x{height}.png"), full_page=True)

        page.set_viewport_size({"width": 1440, "height": 900})
        page.locator("[data-switcher-open]").click()
        page.wait_for_selector('[data-switcher-drawer][aria-hidden="false"]')
        page.screenshot(path=str(output / "viewer-switcher.png"), full_page=True)
        result = {"requests": counters, "initial": initial, "afterTyping": after_typing, "final": final, "recovery": recovery}
        result["responsive"] = responsive
        (output / "contract.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2))
        browser.close()


if __name__ == "__main__":
    main()
