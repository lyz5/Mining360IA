"""Responsive, lifecycle and interaction checks for the premium generic report viewer."""

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
from django.urls import reverse
from playwright.sync_api import sync_playwright

from reports.models import PowerBIReport, ReportingReportPreference


HOST = "mining360-dev.neemba.local"
BASE_URL = f"https://{HOST}"


def session_cookie() -> str:
    user = get_user_model().objects.filter(is_superuser=True, is_active=True).first()
    if not user:
        raise RuntimeError("An active superuser is required for the browser check.")
    client = Client()
    client.force_login(user)
    return client.cookies[settings.SESSION_COOKIE_NAME].value


def report_ids() -> list[str]:
    visible_ids = set(ReportingReportPreference.objects.filter(is_visible=True).values_list("report_id", flat=True))
    return list(PowerBIReport.objects.filter(
        report_id__in=visible_ids,
        is_active=True,
        launch_mode="generic_powerbi",
    ).exclude(embed_url="").values_list("report_id", flat=True)[:3])


def main() -> None:
    reports = report_ids()
    if not reports:
        raise RuntimeError("At least one visible configured generic report is required.")
    output = Path(".artifacts/report-viewer")
    output.mkdir(parents=True, exist_ok=True)
    cookie = session_cookie()
    sizes = (
        (1920, 1080), (1600, 900), (1440, 900), (1366, 768),
        (1280, 800), (1024, 768), (768, 1024), (390, 844),
    )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        )
        context = browser.new_context(ignore_https_errors=True)
        context.add_cookies([{
            "name": settings.SESSION_COOKIE_NAME,
            "value": cookie,
            "domain": HOST,
            "path": "/",
            "secure": True,
            "httpOnly": True,
            "sameSite": "Lax",
        }])
        page = context.new_page()
        page.set_default_timeout(60_000)
        page.set_default_navigation_timeout(120_000)
        page_errors: list[str] = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))

        url = BASE_URL + reverse("report-detail", args=[reports[0]])
        for width, height in sizes:
            page_errors.clear()
            page.set_viewport_size({"width": width, "height": height})
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_selector("[data-report-viewer]", state="visible")
            page.wait_for_selector("[data-canvas-workspace]", state="visible")
            page.wait_for_timeout(2500)
            result = page.evaluate("""
                () => {
                    const shell = document.querySelector('[data-report-viewer]');
                    const header = document.querySelector('.report-workspace-header');
                    const canvas = document.querySelector('[data-canvas-workspace]');
                    const visible = node => node && !node.hidden && getComputedStyle(node).display !== 'none';
                    const intersects = (a, b) => a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
                    const headerItems = [...header.children].filter(visible).map(node => node.getBoundingClientRect());
                    return {
                        pageOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
                        bodyOverflow: document.body.scrollWidth > document.body.clientWidth + 1,
                        shellOverflow: shell.scrollWidth > shell.clientWidth + 1,
                        canvasWidth: Math.round(canvas.getBoundingClientRect().width),
                        canvasHeight: Math.round(canvas.getBoundingClientRect().height),
                        canvasBottom: Math.round(canvas.getBoundingClientRect().bottom),
                        viewportHeight: innerHeight,
                        headerOverlap: headerItems.some((box, index) => headerItems.slice(index + 1).some(other => intersects(box, other))),
                        fixedHeight: getComputedStyle(canvas).height === '700px',
                    };
                }
            """)
            if page_errors:
                raise AssertionError(f"JavaScript error at {width}x{height}: {page_errors}")
            if result["pageOverflow"] or result["bodyOverflow"] or result["shellOverflow"] or result["headerOverlap"]:
                raise AssertionError(f"Viewer overlap/overflow at {width}x{height}: {result}")
            if result["canvasWidth"] < min(300, width - 24) or result["canvasHeight"] < 250:
                raise AssertionError(f"Canvas is not using the viewport at {width}x{height}: {result}")
            if result["canvasBottom"] > result["viewportHeight"] + 1 or result["fixedHeight"]:
                raise AssertionError(f"Canvas height failure at {width}x{height}: {result}")
            page.screenshot(path=str(output / f"viewer-{width}x{height}.png"), full_page=True)
            print(f"PASS viewer {width}x{height}: {result['canvasWidth']}x{result['canvasHeight']}")

        page_errors.clear()
        page.set_viewport_size({"width": 1366, "height": 768})
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_selector('[data-period="custom"]')
        page.locator('[data-period="custom"]').click()
        page.wait_for_selector("[data-custom-range]", state="visible")
        page.locator('.report-canvas-toolbar [data-fullscreen-toggle]').click()
        page.wait_for_function("() => Boolean(document.fullscreenElement)")
        fullscreen = page.evaluate("""
            () => {
                const fullscreen = document.fullscreenElement;
                const toolbar = fullscreen.querySelector('.report-canvas-toolbar');
                const visible = node => node && !node.hidden && getComputedStyle(node).display !== 'none';
                const intersects = (a, b) => a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
                const controls = [...toolbar.querySelectorAll('.period-control-group, .custom-date-range, .report-filter-actions, .viewer-fit-selector, .canvas-toolbar-actions')]
                    .filter(visible).map(node => node.getBoundingClientRect());
                return {
                    commandInsideFullscreen: fullscreen.contains(toolbar.querySelector('[data-command-bar]')),
                    customVisible: visible(toolbar.querySelector('[data-custom-range]')),
                    periodOptions: toolbar.querySelectorAll('[data-period]').length,
                    fitOptions: toolbar.querySelectorAll('[data-fit-mode]').length,
                    toolbarOverflow: toolbar.scrollWidth > toolbar.clientWidth + 1,
                    overlap: controls.some((box, index) => controls.slice(index + 1).some(other => intersects(box, other))),
                };
            }
        """)
        if page_errors or not fullscreen["commandInsideFullscreen"] or not fullscreen["customVisible"]:
            raise AssertionError(f"Fullscreen filter failure: {fullscreen}, errors={page_errors}")
        if fullscreen["periodOptions"] != 3 or fullscreen["fitOptions"] != 3 or fullscreen["toolbarOverflow"] or fullscreen["overlap"]:
            raise AssertionError(f"Fullscreen toolbar overlap/overflow: {fullscreen}")
        page.screenshot(path=str(output / "viewer-fullscreen-custom.png"))
        page.evaluate("document.exitFullscreen()")
        print("PASS fullscreen Custom filters and Fit controls")

        page.set_viewport_size({"width": 1440, "height": 900})
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_selector("[data-switcher-open]")
        page.locator("[data-switcher-open]").click()
        page.wait_for_selector('[data-switcher-drawer][aria-hidden="false"]')
        page.screenshot(path=str(output / "viewer-switcher.png"), full_page=True)
        page.locator("[data-drawer-close]").first.click()
        page.locator("[data-focus-toggle]").click()
        if not page.locator("body").evaluate("node => node.classList.contains('viewer-focus')"):
            raise AssertionError("Focus Mode did not activate.")
        page.screenshot(path=str(output / "viewer-focus.png"), full_page=True)

        for index, report_id in enumerate(reports[1:], start=2):
            page.goto(BASE_URL + reverse("report-detail", args=[report_id]), wait_until="domcontentloaded")
            page.wait_for_selector("[data-report-viewer]")
            page.wait_for_timeout(1500)
            page.screenshot(path=str(output / f"viewer-report-{index}.png"), full_page=True)

        page.goto(BASE_URL + reverse("reporting-config-home"), wait_until="domcontentloaded")
        page.wait_for_selector("[data-report-config-workspace]")
        page.locator("[data-report-list] [data-report-id]").first.click()
        page.wait_for_selector('[data-editor-content]:not([hidden])')
        page.locator('[data-tab="viewer"]').click()
        page.wait_for_selector('[data-panel="viewer"]:not([hidden])')
        if page.locator('[name="viewer_default_period"]').count() != 1:
            raise AssertionError("Viewer Experience configuration fields did not render.")
        scrolled = page.locator("[data-config-form]").evaluate("""
            element => {
                const before = element.scrollTop;
                element.scrollTop = element.scrollHeight;
                return {before, after: element.scrollTop, scrollHeight: element.scrollHeight, clientHeight: element.clientHeight};
            }
        """)
        if scrolled["scrollHeight"] > scrolled["clientHeight"] and scrolled["after"] <= scrolled["before"]:
            raise AssertionError(f"Configuration editor does not scroll: {scrolled}")
        page.screenshot(path=str(output / "viewer-experience-configuration.png"), full_page=True)
        print("PASS Viewer Experience configuration tab")
        browser.close()


if __name__ == "__main__":
    main()
