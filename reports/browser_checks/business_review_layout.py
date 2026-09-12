"""Responsive and failure-isolation checks for the Business Review control tower."""

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


def cookie():
    user = get_user_model().objects.filter(is_superuser=True, is_active=True).first()
    client = Client()
    client.force_login(user)
    return client.cookies[settings.SESSION_COOKIE_NAME].value


def fixtures(url):
    overview = {
        "ready": True,
        "context": {"published_mapping_version": 4, "period": "YTD", "period_year": 2026},
        "freshness": {"review_generated_at": "2026-09-05T13:00:00Z", "revenue_snapshot_at": "2026-09-05T13:00:00Z", "fleet_snapshot_at": "2026-09-05T13:00:00Z"},
        "confidence": {"status": "Moderate", "account_coverage": 82.4, "revenue_coverage": 71.3, "fleet_coverage": 76.8, "warnings": ["Revenue coverage is limited to 71.3%."]},
        "metrics": {"mining_revenue_ytd_eur": 375000000, "revenue_change_pct": 8.4, "fleet_count": 1738, "revenue_per_equipment_eur": 215765, "unallocated_revenue_eur": 50385709, "revenue_by_lob": {"PRIME": 169663828, "PARTS": 175744466, "SERVICE": 17628815, "RENTAL": 13262294}},
        "changes": {"added": [{}, {}, {}], "changed": [{}], "removed": []},
        "attention_items": [{"risk_code": "HIGH_UNALLOCATED_REVENUE", "severity": "High"}],
    }
    portfolio = {"ready": True, "thresholds": {"status": "READY", "method": "Fixed Governed Threshold", "rule_version": "1.0", "revenue_threshold": 30000000, "fleet_threshold": 100}, "results": [
        {"entity_id": "11111111-1111-1111-1111-111111111111", "name": "Fekola", "fleet": 217, "revenue": 22800000, "revenue_per_equipment": 105069, "account_count": 4, "classification": "Commercial Opportunity"},
        {"entity_id": "22222222-2222-2222-2222-222222222222", "name": "Essakane", "fleet": 186, "revenue": 48700000, "revenue_per_equipment": 261828, "account_count": 5, "classification": "Strategic Account"},
        {"entity_id": "33333333-3333-3333-3333-333333333333", "name": "Bonikro", "fleet": 74, "revenue": 18200000, "revenue_per_equipment": 245946, "account_count": 3, "classification": "Low Priority"},
    ]}
    if "/overview/" in url:
        return overview
    if "/portfolio/" in url:
        return portfolio
    if "/opportunities/" in url:
        return {"ready": True, "results": [{"id": "1", "code": "HIGH_FLEET_LOW_PARTS_REVENUE", "minesite": "Fekola", "severity": "High", "status": "Open"}]}
    if "/risks/" in url:
        return {"ready": True, "results": [{"id": "1", "code": "HIGH_UNALLOCATED_REVENUE", "severity": "High", "status": "Open"}]}
    if "/accounts/" in url:
        return {"ready": True, "results": [{"id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "name": "Fekola Account", "code": "ACC-001", "minesites": ["Fekola"], "roles": ["Billing Account"], "source_record_count": 3}]}
    if "/minesites/" in url:
        return {"ready": True, "results": portfolio["results"]}
    if "/actions/" in url:
        return {"ready": True, "results": [{"id": "1", "title": "Review Parts capture", "priority": "High", "status": "In Progress", "account": "Fekola Account", "minesite": "Fekola", "owner": "Sales Manager", "due_date": "2026-09-12"}]}
    return {"ready": True, "results": []}


def main():
    output = PROJECT_ROOT / ".artifacts" / "business-review"
    output.mkdir(parents=True, exist_ok=True)
    session_cookie = cookie()
    server = make_server("127.0.0.1", 8123, StaticFilesHandler(get_wsgi_application()))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
            context = browser.new_context()
            context.add_cookies([{"name": settings.SESSION_COOKIE_NAME, "value": session_cookie, "domain": "127.0.0.1", "path": "/", "httpOnly": True, "sameSite": "Lax"}])
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("**/api/business-review/**", lambda route: route.fulfill(json=fixtures(route.request.url)))
            for width, height in ((1440, 900), (1024, 768), (768, 1024), (390, 844)):
                page.set_viewport_size({"width": width, "height": height})
                page.goto("http://127.0.0.1:8123/business-review/", wait_until="networkidle")
                page.wait_for_selector("[data-br-ready]:visible")
                checks = page.evaluate("""() => ({
                    overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
                    revenue: document.querySelector('[data-br-metric="mining_revenue_ytd_eur"]')?.textContent,
                    version: document.querySelector('[data-br-version]')?.textContent,
                    points: document.querySelectorAll('.br-matrix-point').length,
                    technicalControls: Boolean(document.querySelector('[data-bm-sync], [data-bm-confirm]')),
                    widest: [...document.querySelectorAll('body *')].filter(node => node.getBoundingClientRect().right > innerWidth + 1).slice(0, 5).map(node => `${node.tagName}.${node.className}:${Math.round(node.getBoundingClientRect().right)}:${node.textContent.trim().slice(0, 35)}`),
                })""")
                if checks["overflow"] or checks["points"] != 3 or checks["technicalControls"] or "Version 4" not in checks["version"]:
                    raise AssertionError(f"Business Review layout failed at {width}x{height}: {checks}")
                page.screenshot(path=str(output / f"business-review-overview-{width}x{height}.png"), full_page=True)
                page.locator('[data-br-tab="portfolio"]').click()
                page.screenshot(path=str(output / f"business-review-portfolio-{width}x{height}.png"), full_page=True)
                print(f"PASS {width}x{height}: {checks}")
            if errors:
                raise AssertionError(errors)
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
