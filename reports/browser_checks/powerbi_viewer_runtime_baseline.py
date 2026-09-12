"""Capture a sanitized Power BI viewer request and lifecycle baseline."""

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

from reports.models import PowerBIReport, ReportingReportPreference


BASE_URL = os.getenv("MINING360_BROWSER_BASE_URL", "http://127.0.0.1:8001")


def session_cookie() -> str:
    user = get_user_model().objects.filter(is_superuser=True, is_active=True).first()
    if not user:
        raise RuntimeError("An active superuser is required for the browser check.")
    client = Client()
    client.force_login(user)
    return client.cookies[settings.SESSION_COOKIE_NAME].value


def reports() -> list[tuple[str, str]]:
    visible = set(
        ReportingReportPreference.objects.filter(is_visible=True)
        .values_list("report_id", flat=True)
    )
    return list(
        PowerBIReport.objects.filter(
            report_id__in=visible,
            is_active=True,
            launch_mode="generic_powerbi",
            validation_status="Validated",
        )
        .exclude(embed_url="")
        .values_list("report_id", "display_name")[:3]
    )


def safe_url(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


INSTRUMENTATION = r"""
(() => {
    const metrics = window.__viewerBaseline = {
        startedAt: performance.now(), constructors: 0, embedCalls: 0,
        resetCalls: 0, configRequests: 0, filterApplyCalls: 0,
        pageChangeCalls: 0, fitModeCalls: 0, tokenSchedules: 0, events: [], fetches: []
    };
    let runtimeValue;
    Object.defineProperty(window, 'Mining360PowerBIEmbed', {
        configurable: true,
        get: () => runtimeValue,
        set: value => {
            runtimeValue = value;
            if (!value || value.__baselineWrapped) return;
            const Original = value;
            class InstrumentedRuntime extends Original {
                constructor(...args) { super(...args); metrics.constructors += 1; }
            }
            for (const [name, counter] of [
                ['embed', 'embedCalls'], ['reset', 'resetCalls'],
                ['requestConfig', 'configRequests'], ['applyFilters', 'filterApplyCalls'],
                ['setActivePage', 'pageChangeCalls'], ['setFitMode', 'fitModeCalls'],
                ['scheduleTokenRefresh', 'tokenSchedules']
            ]) {
                const original = InstrumentedRuntime.prototype[name];
                if (typeof original !== 'function') continue;
                InstrumentedRuntime.prototype[name] = function(...args) {
                    metrics[counter] += 1;
                    return original.apply(this, args);
                };
            }
            const originalEmit = InstrumentedRuntime.prototype.emit;
            InstrumentedRuntime.prototype.emit = function(type, details) {
                metrics.events.push({type, at: Math.round(performance.now() - metrics.startedAt)});
                return originalEmit.call(this, type, details);
            };
            InstrumentedRuntime.__baselineWrapped = true;
            runtimeValue = InstrumentedRuntime;
        }
    });
    const originalFetch = window.fetch.bind(window);
    window.fetch = async (...args) => {
        const input = args[0];
        const url = typeof input === 'string' ? input : (input?.url || String(input));
        const started = performance.now();
        try {
            const response = await originalFetch(...args);
            metrics.fetches.push({url: new URL(url, location.origin).pathname, status: response.status,
                durationMs: Math.round(performance.now() - started), serverTiming: response.headers.get('server-timing') || ''});
            return response;
        } catch (error) {
            metrics.fetches.push({url: new URL(url, location.origin).pathname, status: 0,
                durationMs: Math.round(performance.now() - started), error: error.name});
            throw error;
        }
    };
    window.addEventListener('mining360:report-ready', event => {
        metrics.ready = event.detail;
        metrics.readyAt = Math.round(performance.now() - metrics.startedAt);
    });
})();
"""


def main() -> None:
    selected = reports()
    if not selected:
        raise RuntimeError("No visible validated generic Power BI report is configured.")
    output = PROJECT_ROOT / ".artifacts" / "powerbi-viewer-baseline"
    output.mkdir(parents=True, exist_ok=True)
    results = []
    cookie = session_cookie()
    host = urlsplit(BASE_URL).hostname or "127.0.0.1"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        )
        context = browser.new_context(ignore_https_errors=True, viewport={"width": 1440, "height": 900})
        context.add_cookies([{
            "name": settings.SESSION_COOKIE_NAME, "value": cookie,
            "domain": host, "path": "/", "httpOnly": True, "sameSite": "Lax",
        }])
        context.add_init_script(INSTRUMENTATION)

        for index, (report_id, name) in enumerate(selected):
            page = context.new_page()
            network = []
            console_errors = []
            page.on("request", lambda request, rows=network: rows.append({
                "event": "request", "at": time.time(), "method": request.method,
                "url": safe_url(request.url), "resource_type": request.resource_type,
            }))
            page.on("response", lambda response, rows=network: rows.append({
                "event": "response", "at": time.time(), "status": response.status,
                "url": safe_url(response.url),
            }))
            page.on("pageerror", lambda error, rows=console_errors: rows.append(str(error)))
            started = time.perf_counter()
            url = BASE_URL + reverse("report-detail", args=[report_id])
            page.goto(url, wait_until="domcontentloaded", timeout=120_000)
            shell_ms = round((time.perf_counter() - started) * 1000)
            page.wait_for_selector("[data-report-viewer]", state="visible")
            try:
                page.wait_for_function(
                    "() => Boolean(window.__viewerBaseline.ready || document.querySelector('[data-runtime-error]:not([hidden])'))",
                    timeout=150_000,
                )
            except Exception:
                pass
            page.wait_for_timeout(1_000)
            metrics = page.evaluate("window.__viewerBaseline")
            error_visible = page.locator("[data-runtime-error]:not([hidden])").count() > 0
            metrics.update({
                "report_id": report_id, "report_name": name, "shell_ms": shell_ms,
                "runtime_error_visible": error_visible, "console_errors": console_errors,
                "network_request_count": len([row for row in network if row["event"] == "request"]),
                "viewer_config_network_count": sum("viewer-configuration" in row["url"] for row in network if row["event"] == "request"),
                "embed_config_network_count": sum("embed-config" in row["url"] for row in network if row["event"] == "request"),
            })
            results.append(metrics)
            (output / f"network-{index + 1}.json").write_text(json.dumps(network, indent=2), encoding="utf-8")
            page.screenshot(path=str(output / f"viewer-{index + 1}.png"), full_page=True)
            page.close()

        browser.close()

    (output / "baseline.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
