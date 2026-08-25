"""Responsive overlap check for the Availability Command Center control bar."""

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


VIEWPORTS = (
    (1920, 1080),
    (1600, 900),
    (1440, 900),
    (1366, 768),
    (1280, 800),
    (1024, 768),
    (768, 1024),
    (390, 844),
)


def authenticated_session_cookie() -> str:
    user = get_user_model().objects.filter(is_superuser=True, is_active=True).first()
    if not user:
        raise RuntimeError("An active superuser is required for the browser layout check.")
    client = Client()
    client.force_login(user)
    return client.cookies[settings.SESSION_COOKIE_NAME].value


def main() -> None:
    output_dir = Path(".artifacts/homepage-control-bar")
    output_dir.mkdir(parents=True, exist_ok=True)
    cookie = authenticated_session_cookie()
    base_url = "https://mining360-dev.neemba.local/"

    with sync_playwright() as playwright:
        edge_path = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
        browser = playwright.chromium.launch(headless=True, executable_path=str(edge_path))
        loader_context = browser.new_context(
            ignore_https_errors=True,
            java_script_enabled=False,
            viewport={"width": 1440, "height": 900},
        )
        loader_context.add_cookies([{
            "name": settings.SESSION_COOKIE_NAME,
            "value": cookie,
            "domain": "mining360-dev.neemba.local",
            "path": "/",
            "secure": True,
            "httpOnly": True,
            "sameSite": "Lax",
        }])
        loader_page = loader_context.new_page()
        loader_page.goto(base_url, wait_until="networkidle", timeout=60_000)
        loader_page.wait_for_selector("[data-brand-loader]", state="visible", timeout=30_000)
        assert loader_page.locator(".homepage-brand-loader__content img").evaluate(
            "image => image.complete && image.naturalWidth > 0"
        )
        loader_page.screenshot(path=str(output_dir / "neemba-brand-loader.png"), full_page=True)
        loader_context.close()
        print("PASS Neemba branded initial loader")

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

        for width, height in VIEWPORTS:
            page.set_viewport_size({"width": width, "height": height})
            page.goto(base_url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_selector(".availability-control-grid", state="visible", timeout=30_000)
            page.wait_for_function(
                "document.querySelector('[data-context-controls]')?.hidden === false",
                timeout=30_000,
            )
            page.wait_for_timeout(1_200)
            result = page.evaluate("""
                () => {
                    const toolbar = document.querySelector('.availability-control-grid');
                    const selectors = [
                        '.period-group', '.minesite-group',
                        '.model-group', '.equipment-group', '.reset-group'
                    ];
                    const nodes = selectors.map((selector) => document.querySelector(selector))
                        .filter((node) => node && !node.hidden);
                    const boxes = nodes.map((node) => ({
                        name: node.className,
                        rect: node.getBoundingClientRect(),
                    }));
                    const intersections = [];
                    for (let left = 0; left < boxes.length; left += 1) {
                        for (let right = left + 1; right < boxes.length; right += 1) {
                            const a = boxes[left].rect;
                            const b = boxes[right].rect;
                            const overlaps = a.left < b.right - 1 && a.right > b.left + 1
                                && a.top < b.bottom - 1 && a.bottom > b.top + 1;
                            if (overlaps) intersections.push([boxes[left].name, boxes[right].name]);
                        }
                    }
                    const detachedLabels = nodes.filter((node) => {
                        const label = node.querySelector('.control-label, :scope > span');
                        const control = node.querySelector('.segmented-control, select, button');
                        if (!label || !control) return false;
                        return label.getBoundingClientRect().bottom > control.getBoundingClientRect().top + 1;
                    }).map((node) => node.className);
                    const toolbarRect = toolbar.getBoundingClientRect();
                    const resetRect = document.querySelector('.reset-group').getBoundingClientRect();
                    return {
                        pageOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
                        toolbarOverflow: toolbar.scrollWidth > toolbar.clientWidth + 1,
                        resetClipped: resetRect.left < toolbarRect.left - 1 || resetRect.right > toolbarRect.right + 1,
                        intersections,
                        detachedLabels,
                        dimensions: boxes.map((box) => ({
                            name: box.name,
                            left: Math.round(box.rect.left),
                            right: Math.round(box.rect.right),
                            width: Math.round(box.rect.width),
                            scrollWidth: document.querySelector(`.${String(box.name).split(' ').join('.')}`)?.scrollWidth,
                            clientWidth: document.querySelector(`.${String(box.name).split(' ').join('.')}`)?.clientWidth,
                        })),
                        toolbarDimensions: { scrollWidth: toolbar.scrollWidth, clientWidth: toolbar.clientWidth },
                    };
                }
            """)
            failures = [
                key for key in ("pageOverflow", "toolbarOverflow", "resetClipped", "intersections", "detachedLabels")
                if result[key]
            ]
            if failures:
                raise AssertionError(f"{width}x{height}: {failures}: {result}")
            page.screenshot(
                path=str(output_dir / f"control-bar-{width}x{height}.png"),
                full_page=True,
            )
            print(f"PASS {width}x{height}")

        page.set_viewport_size({"width": 1024, "height": 768})
        page.goto(base_url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_function(
            "document.querySelector('[data-context-controls]')?.hidden === false",
            timeout=30_000,
        )
        page.wait_for_function(
            "document.querySelector('[data-updating]')?.hidden === true",
            timeout=60_000,
        )
        page.evaluate("""
            () => {
                const stress = {
                    minesite: 'IAMGOLD Essakane Gold Mine Operations',
                    model: 'Caterpillar 777 Off-Highway Truck',
                    equipment: 'A-VERY-LONG-EQUIPMENT-NAME-123456789',
                };
                Object.entries(stress).forEach(([code, value]) => {
                    const select = document.querySelector(`[data-filter="${code}"]`);
                    select.add(new Option(value, value, true, true));
                    select.title = value;
                });
                document.querySelector('[data-period="last_12_months"]').textContent = 'Previous rolling 12 months';
                document.querySelector('[data-reset-filters]').textContent = 'Reset all availability filters';
            }
        """)
        stress_result = page.evaluate("""
            () => {
                const toolbar = document.querySelector('.availability-control-grid');
                const nodes = Array.from(toolbar.querySelectorAll(
                    '.period-group, .minesite-group, .model-group, .equipment-group, .reset-group'
                )).filter((node) => !node.hidden);
                const boxes = nodes.map((node) => ({ name: node.className, rect: node.getBoundingClientRect() }));
                const intersections = [];
                for (let left = 0; left < boxes.length; left += 1) {
                    for (let right = left + 1; right < boxes.length; right += 1) {
                        const a = boxes[left].rect;
                        const b = boxes[right].rect;
                        if (a.left < b.right - 1 && a.right > b.left + 1
                            && a.top < b.bottom - 1 && a.bottom > b.top + 1) {
                            intersections.push([boxes[left].name, boxes[right].name]);
                        }
                    }
                }
                return {
                    pageOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
                    toolbarOverflow: toolbar.scrollWidth > toolbar.clientWidth + 1,
                    intersections,
                };
            }
        """)
        if stress_result["pageOverflow"] or stress_result["toolbarOverflow"] or stress_result["intersections"]:
            raise AssertionError(f"Content stress test failed: {stress_result}")
        page.screenshot(path=str(output_dir / "control-bar-content-stress-en.png"), full_page=True)
        print("PASS content stress / English labels")

        page.set_viewport_size({"width": 1366, "height": 768})
        page.goto(base_url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_selector('[data-filter="equipment"]', state="visible", timeout=30_000)
        assert page.locator('[data-breakdown-control]').count() == 0
        page.wait_for_selector(".trend-value-label", state="visible", timeout=30_000)
        value_labels = page.locator(".trend-value-label").all_text_contents()
        assert len(value_labels) >= 2
        assert all(label.strip().endswith("%") for label in value_labels)
        if page.locator(".trend-target-line").count():
            target_labels = page.locator(".trend-target-label").all_text_contents()
            assert len(target_labels) == 1
            assert target_labels[0].strip().startswith("Target ")
            assert target_labels[0].strip().endswith("%")
        page.wait_for_function(
            "document.querySelector('[data-breakdown-section]')?.hidden === true",
            timeout=10_000,
        )
        page.screenshot(path=str(output_dir / "equipment-filter-without-attention-section.png"), full_page=True)
        print("PASS equipment filter without attention section")
        print(f"PASS trend value labels ({len(value_labels)} points)")
        if page.locator(".trend-target-line").count():
            print(f"PASS trend target label ({target_labels[0]})")

        browser.close()


if __name__ == "__main__":
    main()
