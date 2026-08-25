"""Responsive and interaction validation for the premium Reporting Hub."""

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
        raise RuntimeError("An active superuser is required for the browser check.")
    client = Client()
    client.force_login(user)
    return client.cookies[settings.SESSION_COOKIE_NAME].value


def main() -> None:
    output_dir = Path(".artifacts/reporting-hub")
    output_dir.mkdir(parents=True, exist_ok=True)
    cookie = authenticated_session_cookie()
    sizes = (
        (1920, 1080, 4),
        (1440, 900, 3),
        (1366, 768, 3),
        (1024, 768, 2),
        (390, 844, 1),
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
            "domain": "mining360-dev.neemba.local",
            "path": "/",
            "secure": True,
            "httpOnly": True,
            "sameSite": "Lax",
        }])
        page = context.new_page()
        page.set_default_navigation_timeout(120_000)
        page.set_default_timeout(60_000)

        for width, height, expected_columns in sizes:
            page.set_viewport_size({"width": width, "height": height})
            page.goto("https://mining360-dev.neemba.local/reporting/", wait_until="domcontentloaded")
            page.wait_for_selector("[data-reporting-hub]", state="visible", timeout=60_000)
            page.wait_for_selector("[data-report-card]", state="visible", timeout=60_000)
            result = page.evaluate("""
                () => {
                    const visibleCards = [...document.querySelectorAll('[data-report-card]')]
                        .filter(card => !card.hidden);
                    const firstTop = visibleCards[0]?.getBoundingClientRect().top;
                    const firstRow = visibleCards.filter(card =>
                        Math.abs(card.getBoundingClientRect().top - firstTop) < 2
                    );
                    const boxes = firstRow.map(card => card.getBoundingClientRect());
                    const sidebar = document.querySelector('.app-nav')?.getBoundingClientRect();
                    const hub = document.querySelector('[data-reporting-hub]')?.getBoundingClientRect();
                    const overlap = boxes.some((box, index) => boxes.slice(index + 1).some(other =>
                        box.left < other.right && box.right > other.left &&
                        box.top < other.bottom && box.bottom > other.top
                    ));
                    return {
                        cards: visibleCards.length,
                        columns: firstRow.length,
                        overlap,
                        pageOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
                        toolbarOverflow: document.querySelector('.reporting-toolbar').scrollWidth >
                            document.querySelector('.reporting-toolbar').clientWidth + 1,
                        sidebarOverlap: window.innerWidth > 700 && sidebar && hub && hub.left < sidebar.right - 1,
                        missingFavoriteLabels: [...document.querySelectorAll('[data-favorite-button]')]
                            .filter(button => !button.getAttribute('aria-label')).length,
                        brokenImages: [...document.querySelectorAll('[data-report-thumbnail]')]
                            .filter(image => image.complete && image.naturalWidth === 0 && !image.hidden).length,
                        visualIdentities: new Set(visibleCards.map(card => {
                            const visual = card.querySelector('.report-card-visual');
                            return `${visual?.dataset.visualSource || ''}:${visual?.dataset.reportIllustration || ''}:${visual?.className || ''}`;
                        })).size,
                    };
                }
            """)
            if result["cards"] < 1:
                raise AssertionError(f"No report cards at {width}x{height}: {result}")
            if result["columns"] != min(expected_columns, result["cards"]):
                raise AssertionError(f"Unexpected grid at {width}x{height}: {result}")
            if result["overlap"] or result["pageOverflow"] or result["toolbarOverflow"] or result["sidebarOverlap"]:
                raise AssertionError(f"Layout failure at {width}x{height}: {result}")
            if result["missingFavoriteLabels"]:
                raise AssertionError(f"Favorite buttons lack labels at {width}x{height}: {result}")
            if result["brokenImages"]:
                raise AssertionError(f"Broken report images at {width}x{height}: {result}")
            if result["cards"] >= 3 and result["visualIdentities"] < 3:
                raise AssertionError(f"Report identities are not distinct enough at {width}x{height}: {result}")
            page.screenshot(path=str(output_dir / f"reporting-hub-{width}x{height}.png"), full_page=True)
            print(f"PASS Reporting Hub {width}x{height}: {result['columns']} columns")

        page.set_viewport_size({"width": 1440, "height": 900})
        page.goto("https://mining360-dev.neemba.local/reporting/", wait_until="domcontentloaded")
        page.wait_for_selector("[data-report-card]", state="visible", timeout=60_000)
        first_name = page.locator("[data-report-card] h3").first.inner_text()
        page.locator("[data-hub-search]").fill(first_name)
        page.wait_for_timeout(600)
        if page.locator("[data-report-card]:visible").count() != 1:
            raise AssertionError("Debounced report search did not narrow the catalog.")
        if "q=" not in page.url:
            raise AssertionError("Search state was not persisted in the URL.")
        page.screenshot(path=str(output_dir / "reporting-hub-search.png"), full_page=True)

        page.locator("[data-empty-clear]").evaluate("element => element.click()")
        page.wait_for_timeout(500)
        page.locator('[data-view="list"]').click()
        if not page.locator("[data-report-catalog]").evaluate("element => element.classList.contains('is-list')"):
            raise AssertionError("List view was not applied.")
        page.screenshot(path=str(output_dir / "reporting-hub-list.png"), full_page=True)
        print("PASS search, URL persistence and list view")
        browser.close()


if __name__ == "__main__":
    main()
