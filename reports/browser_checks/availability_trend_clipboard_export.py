"""Validate Availability Trend high-resolution PNG clipboard export."""

from __future__ import annotations

import base64
import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Mining360IA.settings")

import django

django.setup()

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client
from playwright.sync_api import sync_playwright


BASE_URL = os.environ.get("MINING360_BROWSER_BASE_URL", "http://127.0.0.1:8000/")


def authenticated_cookie() -> str:
    user = get_user_model().objects.filter(is_superuser=True, is_active=True).first()
    if not user:
        raise RuntimeError("An active superuser is required for the clipboard check.")
    client = Client()
    client.force_login(user)
    return client.cookies[settings.SESSION_COOKIE_NAME].value


def main() -> None:
    output_dir = PROJECT_ROOT / ".artifacts" / "availability-trend-export"
    output_dir.mkdir(parents=True, exist_ok=True)
    cookie = authenticated_cookie()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        )
        context = browser.new_context(ignore_https_errors=True, viewport={"width": 1440, "height": 900})
        context.grant_permissions(["clipboard-read", "clipboard-write"], origin=BASE_URL.rstrip("/"))
        host = BASE_URL.split("://", 1)[1].split("/", 1)[0].split(":", 1)[0]
        context.add_cookies([{
            "name": settings.SESSION_COOKIE_NAME,
            "value": cookie,
            "domain": host,
            "path": "/",
            "secure": BASE_URL.startswith("https://"),
            "httpOnly": True,
            "sameSite": "Lax",
        }])
        page = context.new_page()
        page.on("pageerror", lambda error: print(f"PAGE ERROR: {error}"))
        page.on("console", lambda message: print(f"CONSOLE {message.type}: {message.text}") if message.type in {"error", "warning"} else None)
        page.on("response", lambda response: print(f"HTTP {response.status}: {response.url}") if response.status >= 400 else None)
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=90_000)
        try:
            page.wait_for_selector("[data-copy-availability-trend]", state="visible", timeout=30_000)
        except Exception:
            page.screenshot(path=str(output_dir / "copy-action-missing.png"), full_page=True)
            body = page.locator("body").inner_text()[:1000].encode("ascii", "backslashreplace").decode("ascii")
            print(f"DEBUG URL: {page.url}\nDEBUG BODY: {body}")
            raise
        try:
            page.wait_for_selector("[data-copy-availability-trend]:not([disabled])", state="visible", timeout=45_000)
        except Exception:
            page.screenshot(path=str(output_dir / "clipboard-export-failure.png"), full_page=True)
            print("DEBUG:", page.evaluate("""
                () => ({
                    ready: document.querySelector('[data-export-visual]')?.dataset.exportReady,
                    disabled: document.querySelector('[data-copy-availability-trend]')?.disabled,
                    points: document.querySelectorAll('[data-trend-index]').length,
                    error: document.querySelector('[data-error-message]')?.textContent,
                    exporter: typeof window.Mining360VisualExport,
                })
            """))
            raise
        png_probe = page.evaluate("""
            async () => {
                try {
                    const target = document.querySelector('[data-export-visual="availability-trend"]');
                    const blob = await window.Mining360VisualExport.createPng(target, { scale: 2, background: '#ffffff' });
                    return { ok: true, type: blob.type, size: blob.size };
                } catch (error) {
                    return { ok: false, name: error.name, code: error.code, message: error.message, stack: error.stack };
                }
            }
        """)
        print(f"PNG PROBE: {png_probe}")
        assert png_probe.get("ok") and png_probe.get("type") == "image/png" and png_probe.get("size", 0) > 10_000, png_probe
        page.locator("[data-copy-availability-trend]").click()
        page.wait_for_selector("[data-visual-export-notice]", state="visible", timeout=30_000)
        notice = page.locator("[data-visual-export-notice]").inner_text()
        assert notice == "Chart copied. Paste it into PowerPoint with Ctrl+V.", notice

        clipboard = page.evaluate("""
            async () => {
                const items = await navigator.clipboard.read();
                const pngItem = items.find(item => item.types.includes('image/png'));
                if (!pngItem) return { types: items.flatMap(item => item.types) };
                const blob = await pngItem.getType('image/png');
                const bitmap = await createImageBitmap(blob);
                const bytes = new Uint8Array(await blob.arrayBuffer());
                let binary = '';
                for (let offset = 0; offset < bytes.length; offset += 0x8000) {
                    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
                }
                return {
                    types: pngItem.types,
                    size: blob.size,
                    width: bitmap.width,
                    height: bitmap.height,
                    base64: btoa(binary),
                };
            }
        """)
        assert "image/png" in clipboard.get("types", []), clipboard
        assert clipboard["size"] > 10_000, clipboard
        panel = page.locator("[data-export-visual='availability-trend']").bounding_box()
        assert panel, "Availability Trend export boundary is unavailable."
        assert clipboard["width"] >= int(panel["width"] * 1.9), (clipboard, panel)
        assert clipboard["height"] >= int(panel["height"] * 1.9), (clipboard, panel)
        (output_dir / "availability-trend-copied.png").write_bytes(base64.b64decode(clipboard["base64"]))

        page.wait_for_selector("[data-copy-physical-availability]:not([disabled])", state="visible", timeout=30_000)
        page.evaluate("document.querySelector('[data-visual-export-notice]')?.remove()")
        page.locator("[data-copy-physical-availability]").click()
        page.wait_for_selector("[data-visual-export-notice]", state="visible", timeout=30_000)
        availability_notice = page.locator("[data-visual-export-notice]").inner_text()
        assert availability_notice == "Chart copied. Paste it into PowerPoint with Ctrl+V.", availability_notice
        availability_clipboard = page.evaluate("""
            async () => {
                const items = await navigator.clipboard.read();
                const pngItem = items.find(item => item.types.includes('image/png'));
                if (!pngItem) return { types: items.flatMap(item => item.types) };
                const blob = await pngItem.getType('image/png');
                const bitmap = await createImageBitmap(blob);
                const bytes = new Uint8Array(await blob.arrayBuffer());
                let binary = '';
                for (let offset = 0; offset < bytes.length; offset += 0x8000) {
                    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
                }
                return {
                    types: pngItem.types,
                    size: blob.size,
                    width: bitmap.width,
                    height: bitmap.height,
                    base64: btoa(binary),
                };
            }
        """)
        availability_panel = page.locator("[data-export-visual='physical-availability']").bounding_box()
        assert availability_panel, "Physical Availability export boundary is unavailable."
        assert availability_clipboard["size"] > 10_000, availability_clipboard
        assert availability_clipboard["width"] >= int(availability_panel["width"] * 1.9), (availability_clipboard, availability_panel)
        assert availability_clipboard["height"] >= int(availability_panel["height"] * 1.9), (availability_clipboard, availability_panel)
        (output_dir / "physical-availability-copied.png").write_bytes(
            base64.b64decode(availability_clipboard["base64"])
        )
        page.screenshot(path=str(output_dir / "availability-command-center-copy-action.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(300)
        mobile_layout = page.evaluate("""
            () => ({
                documentWidth: document.documentElement.scrollWidth,
                viewportWidth: document.documentElement.clientWidth,
                button: (() => {
                    const rect = document.querySelector('[data-copy-availability-trend]').getBoundingClientRect();
                    return { width: rect.width, height: rect.height };
                })(),
                availabilityButton: (() => {
                    const rect = document.querySelector('[data-copy-physical-availability]').getBoundingClientRect();
                    return { width: rect.width, height: rect.height };
                })(),
            })
        """)
        assert mobile_layout["documentWidth"] <= mobile_layout["viewportWidth"] + 1, mobile_layout
        assert mobile_layout["button"]["width"] >= 40 and mobile_layout["button"]["height"] >= 40, mobile_layout
        assert mobile_layout["availabilityButton"]["width"] >= 40 and mobile_layout["availabilityButton"]["height"] >= 40, mobile_layout
        page.screenshot(path=str(output_dir / "availability-command-center-copy-action-mobile.png"), full_page=True)
        browser.close()

    print(
        "PASS: clipboard exports are high-resolution image/png files: "
        f"trend {clipboard['width']}x{clipboard['height']} ({clipboard['size']} bytes), "
        f"availability {availability_clipboard['width']}x{availability_clipboard['height']} "
        f"({availability_clipboard['size']} bytes)"
    )


if __name__ == "__main__":
    main()
