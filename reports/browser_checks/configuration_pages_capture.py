"""Capture every top-level page exposed by the Configuration navigation."""

from __future__ import annotations

import json
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
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


BASE_URL = "https://mining360-dev.neemba.local"
PAGES = (
    ("01-data", "/data/", "Data"),
    ("02-sources", "/data-sources/", "Sources"),
    ("03-ai-knowledge-base", "/knowledge-base/", "AI Knowledge Base"),
    ("04-system-config", "/system-config/", "System Config"),
    ("05-ai-config", "/ia-config/", "AI Config"),
    ("06-ai-agents", "/ia-config/agents/", "AI Agents"),
    ("07-api-management", "/ai-config/api-management/", "API Management"),
    ("08-reporting-config", "/config/reporting/", "Reporting Configuration"),
    ("09-deployment-process", "/config/deployment/", "Deployment Process"),
    ("10-openai-api-usage", "/config/openai-usage/", "OpenAI API Usage"),
)


def authenticated_session_cookie() -> str:
    user = get_user_model().objects.filter(is_superuser=True, is_active=True).first()
    if not user:
        raise RuntimeError("An active superuser is required for configuration captures.")
    client = Client()
    client.force_login(user)
    return client.cookies[settings.SESSION_COOKIE_NAME].value


def settle_page(page, slug: str) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=12_000)
    except PlaywrightTimeoutError:
        pass

    if slug == "08-reporting-config":
        try:
            page.wait_for_selector("[data-report-config-workspace]", state="visible", timeout=30_000)
            first_report = page.locator("[data-report-list] button, [data-report-list] [data-report-id]").first
            first_report.wait_for(state="visible", timeout=30_000)
            first_report.click()
            page.wait_for_selector("[data-editor-content]:not([hidden])", state="visible", timeout=30_000)
        except PlaywrightTimeoutError:
            pass

    page.wait_for_timeout(2_000)


def main() -> None:
    output_dir = PROJECT_ROOT / ".artifacts" / "configuration-pages"
    output_dir.mkdir(parents=True, exist_ok=True)
    cookie = authenticated_session_cookie()
    manifest = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        )
        context = browser.new_context(
            ignore_https_errors=True,
            viewport={"width": 1440, "height": 900},
            device_scale_factor=1,
        )
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
        page.set_default_navigation_timeout(60_000)
        page.set_default_timeout(30_000)

        for slug, path, label in PAGES:
            response = page.goto(f"{BASE_URL}{path}", wait_until="domcontentloaded")
            settle_page(page, slug)
            screenshot = output_dir / f"{slug}.png"
            page.screenshot(path=str(screenshot), full_page=False, animations="disabled")
            record = {
                "label": label,
                "url": page.url,
                "status": response.status if response else None,
                "title": page.title(),
                "file": screenshot.name,
                "authenticated": "/login/" not in page.url,
            }
            manifest.append(record)
            print(f"CAPTURED {label}: {screenshot.name} ({record['status']})")

        browser.close()

    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    failures = [item for item in manifest if item["status"] is None or item["status"] >= 400 or not item["authenticated"]]
    if failures:
        raise RuntimeError(f"Invalid configuration captures: {failures}")


if __name__ == "__main__":
    main()
