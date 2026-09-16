from __future__ import annotations

import os
from pathlib import Path
import sys
import threading
from wsgiref.simple_server import make_server


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Mining360IA.settings")
os.environ["ENABLE_CODEX_CHATBOT"] = "Admin Only"
os.environ["ENABLE_CODEX_ADMIN"] = "Admin Only"

import django

django.setup()

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.handlers import StaticFilesHandler
from django.core.wsgi import get_wsgi_application
from django.test import Client
from playwright.sync_api import sync_playwright
from codex_chatbot.models import CodexConversation


def _session_cookie() -> str:
    user = get_user_model().objects.filter(is_superuser=True, is_active=True).first()
    if not user:
        raise RuntimeError("An active superuser is required for the browser check.")
    client = Client()
    client.force_login(user)
    return client.cookies[settings.SESSION_COOKIE_NAME].value


def main() -> None:
    output = Path(".artifacts/codex-phase-b")
    output.mkdir(parents=True, exist_ok=True)
    cookie = _session_cookie()
    user = get_user_model().objects.filter(is_superuser=True, is_active=True).first()
    result_conversation = CodexConversation.objects.filter(
        owner=user,
        runs__result_message__isnull=False,
        runs__evidence__isnull=False,
    ).first()
    server = make_server("127.0.0.1", 8134, StaticFilesHandler(get_wsgi_application()))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            )
            context = browser.new_context()
            context.add_cookies(
                [{
                    "name": settings.SESSION_COOKIE_NAME,
                    "value": cookie,
                    "domain": "127.0.0.1",
                    "path": "/",
                    "httpOnly": True,
                    "sameSite": "Lax",
                }]
            )
            page = context.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            routes = [("/codex-chatbot/", "chatbot"), ("/codex-admin/", "admin")]
            if result_conversation:
                routes.insert(1, (f"/codex-chatbot/c/{result_conversation.id}/", "chatbot-result"))
            for route, name in routes:
                for width, height in ((1440, 900), (390, 844)):
                    page.set_viewport_size({"width": width, "height": height})
                    page.goto(f"http://127.0.0.1:8134{route}", wait_until="networkidle")
                    if page.locator("h1").count() != 1:
                        raise AssertionError(f"Missing title for {name} at {width}px")
                    overflow = page.evaluate(
                        "document.documentElement.scrollWidth > document.documentElement.clientWidth + 1"
                    )
                    if overflow:
                        raise AssertionError(f"Horizontal overflow for {name} at {width}px")
                    if name == "chatbot-result":
                        page.locator(".codex-result").first.wait_for(state="visible")
                        if width == 1440:
                            scroll_state = page.locator("#codex-thread").evaluate(
                                """element => {
                                    const before = element.scrollTop;
                                    element.scrollTop = Math.max(1, element.scrollHeight - element.clientHeight);
                                    return {
                                        before,
                                        after: element.scrollTop,
                                        clientHeight: element.clientHeight,
                                        scrollHeight: element.scrollHeight,
                                        overflowY: getComputedStyle(element).overflowY,
                                    };
                                }"""
                            )
                            if scroll_state["overflowY"] != "auto":
                                raise AssertionError(f"Chat thread overflow is not auto: {scroll_state}")
                            if scroll_state["scrollHeight"] <= scroll_state["clientHeight"]:
                                raise AssertionError(f"Chat thread has no scrollable content: {scroll_state}")
                            if scroll_state["after"] <= 0:
                                raise AssertionError(f"Chat thread did not scroll: {scroll_state}")
                    page.screenshot(path=str(output / f"{name}-{width}x{height}.png"), full_page=True)
                    print(f"PASS {name} {width}x{height}")
            if errors:
                raise AssertionError(f"Browser errors: {errors}")
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
