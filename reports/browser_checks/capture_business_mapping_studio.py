"""Capture every Business Mapping Studio view for external UX review."""

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


OUTPUT = PROJECT_ROOT / ".artifacts" / "business-mapping-studio-review-2026-09-05"
BASE_URL = "http://127.0.0.1:8122/data/business-mapping/"


def session_cookie() -> str:
    user = get_user_model().objects.filter(is_superuser=True, is_active=True).first()
    if not user:
        raise RuntimeError("An active superuser is required to capture all governed views.")
    client = Client()
    client.force_login(user)
    return client.cookies[settings.SESSION_COOKIE_NAME].value


def capture() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    cookie = session_cookie()
    server = make_server("127.0.0.1", 8122, StaticFilesHandler(get_wsgi_application()))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            )
            context = browser.new_context(viewport={"width": 1600, "height": 1000}, device_scale_factor=1)
            context.add_cookies([{
                "name": settings.SESSION_COOKIE_NAME,
                "value": cookie,
                "domain": "127.0.0.1",
                "path": "/",
                "httpOnly": True,
                "sameSite": "Lax",
            }])
            page = context.new_page()
            page.goto(BASE_URL, wait_until="networkidle")
            page.wait_for_selector("[data-bm-account-list] .bm-account-row", timeout=30_000)

            # A selected account makes the three-column workspace useful for UX review.
            page.locator("[data-bm-account-list] .bm-account-row").first.click()
            page.wait_for_selector("[data-bm-selected-summary] strong", timeout=15_000)
            page.screenshot(path=str(OUTPUT / "01-mapping-workspace.png"), full_page=True)

            views = (
                ("overview", "02-overview.png"),
                ("conflicts", "03-conflicts.png"),
                ("published", "04-published-versions.png"),
                ("audit", "05-audit-settings.png"),
            )
            for code, filename in views:
                page.locator(f'[data-bm-tab="{code}"]').click()
                page.wait_for_selector(f'[data-bm-panel="{code}"]:visible')
                if code == "conflicts":
                    page.wait_for_function(
                        "document.querySelector('[data-bm-conflicts]')?.textContent.includes('Loading conflicts') === false"
                    )
                page.screenshot(path=str(OUTPUT / filename), full_page=True)

            page.locator('[data-bm-tab="workspace"]').click()
            page.locator('[data-bm-revenue-filter="PARTS"]').click()
            page.wait_for_timeout(750)
            page.screenshot(path=str(OUTPUT / "06-workspace-parts-ytd.png"), full_page=True)

            # Open the confirmation state without committing a mapping.
            page.locator("[data-bm-minesite-search]").fill("Fekola")
            page.wait_for_selector("[data-bm-minesite-results] [data-site-id]", timeout=15_000)
            page.locator("[data-bm-minesite-results] [data-site-id]").first.click()
            page.locator("[data-bm-role]").select_option(label="Billing Account")
            page.locator("[data-bm-valid-from]").fill("2026-01-01")
            page.locator('[data-bm-decision-form] button[type="submit"]').click()
            page.wait_for_selector("[data-bm-validation-dialog]:visible")
            page.screenshot(path=str(OUTPUT / "07-validation-confirmation.png"), full_page=True)

            browser.close()
    finally:
        server.shutdown()
        server.server_close()

    for image in sorted(OUTPUT.glob("*.png")):
        print(image)


if __name__ == "__main__":
    capture()
