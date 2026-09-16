"""Measure the real Business Command Center before and after the V2 refactor."""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from wsgiref.simple_server import make_server


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Mining360IA.settings")
for flag in (
    "ENABLE_BUSINESS_COMMAND_CENTER",
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


def session_cookie() -> str:
    user_model = get_user_model()
    user = user_model.objects.filter(username="papa.diagne@neemba.com", is_active=True).first()
    user = user or user_model.objects.filter(is_superuser=True, is_active=True).first()
    if user is None:
        raise RuntimeError("No active authorized user is available.")
    client = Client()
    client.force_login(user)
    return client.cookies[settings.SESSION_COOKIE_NAME].value


def main() -> None:
    cookie_value = session_cookie()
    server = make_server("127.0.0.1", 8127, StaticFilesHandler(get_wsgi_application()))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    results = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            )
            for width, height, name in (
                (1920, 1080, "desktop-wide"),
                (1440, 900, "desktop"),
                (1366, 768, "laptop"),
                (768, 1024, "tablet"),
                (390, 844, "mobile"),
            ):
                context = browser.new_context(viewport={"width": width, "height": height})
                context.add_cookies([{
                    "name": settings.SESSION_COOKIE_NAME,
                    "value": cookie_value,
                    "domain": "127.0.0.1",
                    "path": "/",
                    "httpOnly": True,
                    "sameSite": "Lax",
                }])
                page = context.new_page()
                requests = []
                page.on("response", lambda response: requests.append({
                    "url": response.url,
                    "status": response.status,
                    "type": response.request.resource_type,
                }) if "/api/business-review/" in response.url else None)
                started = time.perf_counter()
                page.goto(
                    "http://127.0.0.1:8127/business-review/command-center/",
                    wait_until="domcontentloaded",
                    timeout=120_000,
                )
                page.wait_for_selector("[data-content]:visible", timeout=120_000)
                useful_ms = round((time.perf_counter() - started) * 1000, 1)
                page.wait_for_load_state("networkidle", timeout=120_000)
                metrics = page.evaluate("""() => ({
                    documentHeight: document.documentElement.scrollHeight,
                    viewportHeight: window.innerHeight,
                    viewportCount: +(document.documentElement.scrollHeight / window.innerHeight).toFixed(2),
                    documentWidth: document.documentElement.scrollWidth,
                    viewportWidth: document.documentElement.clientWidth,
                    horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
                    machineRows: document.querySelectorAll('[data-machine-body] tr').length,
                    partsRows: document.querySelectorAll('[data-parts-body] tr').length,
                    salesRows: document.querySelectorAll('[data-sales-body] tr').length,
                    leaderRows: document.querySelectorAll('[data-dimension-table] tr').length,
                })""")
                results.append({
                    "viewport": name,
                    "useful_ms": useful_ms,
                    **metrics,
                    "api_requests": requests,
                })
                context.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
