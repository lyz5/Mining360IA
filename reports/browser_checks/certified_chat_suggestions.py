"""Validate the certified new-chat suggestion journey in a real browser."""

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
from reports.models import AIConversation, PlatformUser


BASE_URL = os.getenv("MINING360_BROWSER_BASE_URL", "http://127.0.0.1:8110")


def session_cookie() -> str:
    user, _ = get_user_model().objects.get_or_create(
        username="chat-readiness-browser-check",
        defaults={"is_staff": True, "is_superuser": True, "is_active": True},
    )
    if not user.is_superuser or not user.is_active:
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        user.save(update_fields=["is_staff", "is_superuser", "is_active"])
    PlatformUser.objects.update_or_create(
        django_user=user,
        defaults={
            "azure_ad_id": "chat-readiness-browser-check",
            "user_principal_name": "chat-readiness-browser-check@local.invalid",
            "display_name": "Chat Readiness Browser Check",
            "can_access_ai": True,
            "is_platform_admin": True,
        },
    )
    AIConversation.objects.filter(user=user, status="active").update(status="archived")
    client = Client()
    client.force_login(user)
    return client.cookies[settings.SESSION_COOKIE_NAME].value


def main() -> None:
    output_dir = PROJECT_ROOT / ".artifacts" / "certified-chat-suggestions"
    output_dir.mkdir(parents=True, exist_ok=True)
    cookie = session_cookie()
    host = BASE_URL.split("://", 1)[1].split(":", 1)[0]

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        )
        context = browser.new_context(ignore_https_errors=True, viewport={"width": 1440, "height": 900})
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
        page_errors = []
        console_errors = []
        ask_requests = []
        external_requests = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        page.on("request", lambda request: ask_requests.append(request.url) if "/ai/ask/" in request.url else None)
        page.on("request", lambda request: external_requests.append(request.url) if any(value in request.url for value in ("api.openai.com", "powerautomate", "powerbi.com")) else None)
        page.goto(f"{BASE_URL}/ai/new/", wait_until="domcontentloaded")
        try:
            page.wait_for_selector("[data-certified-suggestion]", state="visible", timeout=15_000)
        except Exception:
            page.screenshot(path=str(output_dir / "new-chat-failed.png"), animations="disabled")
            raise AssertionError({
                "page_errors": page_errors,
                "console_errors": console_errors,
                "empty_state": page.locator(".ai-chat-empty-state").inner_text() if page.locator(".ai-chat-empty-state").count() else "missing",
            })
        labels = page.locator("[data-certified-suggestion]").all_text_contents()
        assert len(labels) == 1, labels
        assert "What can you do" in labels[0], labels
        assert not page.locator("text=Analyze repeated failures").count(), labels
        assert not external_requests, external_requests
        page.screenshot(path=str(output_dir / "new-chat-certified-desktop-1440x900.png"), animations="disabled")

        page.locator("[data-certified-suggestion]").click()
        page.wait_for_selector(".ai-message.assistant:not(.is-failed)", state="visible")
        page.wait_for_selector(".ai-capability-catalog", state="visible")
        assert len(ask_requests) == 1, ask_requests
        assert page.locator(".ai-message.user").count() == 1
        assert page.locator(".ai-message.assistant").count() == 1
        assert not page.locator("text=Response generation failed").count()
        assert not page_errors, page_errors
        page.screenshot(path=str(output_dir / "capability-result-desktop-1440x900.png"), animations="disabled")

        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(250)
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")
        mobile_state = page.evaluate("""() => {
            const selectors = ['.ai-workspace', '.ai-persistent-chat', '.ai-chat-panel', '#ai-chat-thread', '.ai-message.assistant'];
            return Object.fromEntries(selectors.map(selector => {
                const node = document.querySelector(selector);
                if (!node) return [selector, null];
                const box = node.getBoundingClientRect();
                const style = getComputedStyle(node);
                return [selector, {x: box.x, y: box.y, width: box.width, height: box.height, display: style.display, visibility: style.visibility, opacity: style.opacity}];
            }));
        }""")
        assistant_box = mobile_state.get('.ai-message.assistant') or {}
        assert assistant_box.get('width', 0) > 20 and assistant_box.get('height', 0) > 20, mobile_state
        assert assistant_box.get('x', 9999) < 390 and assistant_box.get('y', 9999) < 844, mobile_state
        visible_points = page.evaluate("""() => [[10, 10], [195, 100], [195, 420], [195, 800]].map(([x, y]) => {
            const node = document.elementFromPoint(x, y);
            return node ? `${node.tagName}.${node.className || ''}#${node.id || ''}` : null;
        })""")
        assert any(value and not value.startswith("BODY.") for value in visible_points), {
            "layout": mobile_state,
            "visible_points": visible_points,
        }
        page.screenshot(path=str(output_dir / "capability-result-mobile-390x844.png"), animations="disabled")

        page.set_viewport_size({"width": 1440, "height": 900})
        page.goto(f"{BASE_URL}/ia-config/chat-readiness/", wait_until="domcontentloaded")
        page.wait_for_selector("text=Chatbot Production Readiness", state="visible")
        assert page.locator("text=legacy_analyze_repeated_failures").count()
        assert page.locator("text=Run Production Readiness Suite").count()
        page.screenshot(path=str(output_dir / "production-readiness-dashboard-1440x900.png"), animations="disabled")
        browser.close()

    print(f"PASS: certified suggestion screenshots written to {output_dir}")


if __name__ == "__main__":
    main()
