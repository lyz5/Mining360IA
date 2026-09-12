from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from wsgiref.simple_server import make_server

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Mining360IA.settings")
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

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
    output = Path(".artifacts/invoice-tracking")
    output.mkdir(parents=True, exist_ok=True)
    server = make_server("127.0.0.1", 8125, StaticFilesHandler(get_wsgi_application()))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
            context = browser.new_context()
            context.add_cookies([{"name": settings.SESSION_COOKIE_NAME, "value": session_cookie(), "domain": "127.0.0.1", "path": "/", "httpOnly": True, "sameSite": "Lax"}])
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("**/api/invoice-tracking/overview/", lambda route: route.fulfill(json={
                "ok": True,
                "sync": {"id": "00000000-0000-0000-0000-000000000001", "status": "Completed with Warnings", "progress_percent": 100, "stage_label": "Invoice Tracking buffers and reconciliation completed", "source_status": {"ORDERS": {"rows": 38125}, "DELIVERY_INVOICE": {"rows": 29440}, "INVOICES": {"rows": 12104}, "ACCOUNTING_REVENUE": {"rows": 48002}}, "warnings": [], "errors": []},
                "reconciliation": {"id": "00000000-0000-0000-0000-000000000002", "status": "Completed with Warnings", "rule_version": "draft-neg-llf-v1", "completed_at": "2026-09-07T22:00:00Z", "warnings": [], "summary": {"link_rows_processed": 29440, "status_counts": {"MATCHED": 27120, "PARTIALLY_INVOICED": 1170, "MISSING_ACCOUNTING": 980, "CANCELLED": 170}, "distinct_invoice_headers_matched": 12104, "distinct_accounting_entries_matched": 48002}},
                "can_run": True,
            }))
            rows = [
                {"id": 1, "status": "MATCHED", "confidence": "100.00", "company": "27", "customer": "SNIM", "order_number": "CMD-10482", "order_line": "10", "order_date": "2026-08-01", "part_number": "8E-4567", "delivery_number": "BL-8941", "invoice_number": "FAC-78211", "invoice_date": "2026-08-15", "invoice_status": "Posted", "ordered_quantity": "10", "delivered_quantity": "10", "invoiced_quantity": "10", "line_amount": "18000", "accounting_amount": "18000", "accounting_entry_count": 2, "cancellation_invoice": "", "warnings": [], "matched_by": []},
                {"id": 2, "status": "PARTIALLY_INVOICED", "confidence": "100.00", "company": "33", "customer": "CBG", "order_number": "CMD-10910", "order_line": "20", "order_date": "2026-08-03", "part_number": "1R-1808", "delivery_number": "BL-9002", "invoice_number": "FAC-79001", "invoice_date": "2026-08-20", "invoice_status": "Posted", "ordered_quantity": "20", "delivered_quantity": "12", "invoiced_quantity": "12", "line_amount": "6400", "accounting_amount": "6400", "accounting_entry_count": 1, "cancellation_invoice": "", "warnings": [], "matched_by": []},
                {"id": 3, "status": "MISSING_ACCOUNTING", "confidence": "0.00", "company": "34", "customer": "SMD", "order_number": "CMD-11002", "order_line": "5", "order_date": "2026-08-04", "part_number": "6V-8397", "delivery_number": "BL-9050", "invoice_number": "FAC-79220", "invoice_date": "2026-08-21", "invoice_status": "Posted", "ordered_quantity": "4", "delivered_quantity": "4", "invoiced_quantity": "4", "line_amount": "2100", "accounting_amount": None, "accounting_entry_count": 0, "cancellation_invoice": "", "warnings": [], "matched_by": []},
            ]
            billing_statuses = ["INVOICED", "PARTIALLY_INVOICED", "TO_INVESTIGATE"]
            for row, billing_status in zip(rows, billing_statuses):
                row.update({
                    "view": "orders", "billing_status": billing_status,
                    "operational_status": "Delivered", "branch": "01", "customer_name": row["customer"], "customer_number": row["customer"],
                    "eta": "2026-08-25", "order_type": "Parts", "transport": "Air",
                    "header_order_status": "Delivered", "ca_combine_present": billing_status != "TO_INVESTIGATE",
                    "control_reason": "Invoice Tracking deterministic control",
                })
            page.route("**/api/invoice-tracking/rows/**", lambda route: route.fulfill(json={"ok": True, "view": "orders", "run_id": "run", "count": 3, "page": 1, "pages": 1, "results": rows, "filters": {"companies": ["27", "33", "34"], "statuses": ["INVOICED", "PARTIALLY_INVOICED", "TO_INVESTIGATE"]}}))
            for width, height in ((1440, 900), (390, 844)):
                page.set_viewport_size({"width": width, "height": height})
                page.goto("http://127.0.0.1:8125/invoice-tracking/", wait_until="networkidle")
                page.wait_for_selector("[data-it-rows] tr")
                result = page.evaluate("""() => ({
                    pageOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
                    rowCount: document.querySelectorAll('[data-it-rows] tr').length,
                    tableScrollable: document.querySelector('.it-table-scroll').scrollWidth > document.querySelector('.it-table-scroll').clientWidth,
                    progress: document.querySelector('[data-it-progress]').value,
                })""")
                if result["pageOverflow"] or result["rowCount"] != 3 or result["progress"] != 100:
                    raise AssertionError(f"Invoice Tracking layout failed at {width}x{height}: {result}")
                if width == 390 and not result["tableScrollable"]:
                    raise AssertionError("The detailed table is not independently scrollable on mobile.")
                page.screenshot(path=str(output / f"invoice-tracking-{width}x{height}.png"), full_page=True)
                print(f"PASS {width}x{height}: {result}")
            if errors:
                raise AssertionError(f"Browser errors: {errors}")
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
