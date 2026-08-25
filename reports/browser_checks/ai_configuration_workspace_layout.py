"""Responsive and interaction checks for the AI Configuration workspace."""

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


BASE_URL = "https://mining360-dev.neemba.local/ia-config/"
VIEWPORTS = (
    (1920, 1080), (1600, 900), (1440, 900), (1366, 768),
    (1280, 800), (1024, 768), (768, 1024), (390, 844),
)


def authenticated_session_cookie() -> str:
    user = get_user_model().objects.filter(is_superuser=True, is_active=True).first()
    if not user:
        raise RuntimeError("An active superuser is required for the browser check.")
    client = Client()
    client.force_login(user)
    return client.cookies[settings.SESSION_COOKIE_NAME].value


def assert_layout(page, width: int) -> None:
    result = page.evaluate("""
        () => {
            const workspace = document.querySelector('.aiw-workspace');
            const editor = document.querySelector('.aiw-editor');
            return {
                pageOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
                workspaceOverflow: workspace.scrollWidth > workspace.clientWidth + 1,
                editorOverflow: editor.scrollWidth > editor.clientWidth + 1,
                tableFrameOverflow: document.querySelector('.aiw-table-frame').getBoundingClientRect().right > workspace.getBoundingClientRect().right + 1,
                toolbarOverflow: document.querySelector('.aiw-entity-toolbar').getBoundingClientRect().right > workspace.getBoundingClientRect().right + 1,
                rects: {
                    workspace: workspace.getBoundingClientRect().toJSON(),
                    editor: editor.getBoundingClientRect().toJSON(),
                    table: document.querySelector('.aiw-table-frame').getBoundingClientRect().toJSON(),
                    toolbar: document.querySelector('.aiw-entity-toolbar').getBoundingClientRect().toJSON(),
                },
                bodyClass: document.body.className,
                appNavMode: localStorage.getItem('mining360.aiConfig.appNavMode'),
                healthReady: document.querySelector('[data-health-ready]').textContent,
                scripts: [...document.scripts].map(node => node.src).filter(Boolean),
                controllerAvailable: Boolean(window.Mining360AIConfig),
                primaryAreas: document.querySelectorAll('[data-ai-area]').length,
                visibleEntityGroups: [...document.querySelectorAll('[data-entity-group]')].filter(node => !node.hidden).length,
                permanentTestPanel: Boolean(document.querySelector('.ia-config-test:not([hidden])')),
                permanentControlsPanel: Boolean(document.querySelector('.ia-config-sidebar')),
            };
        }
    """)
    assert not result["pageOverflow"], (width, result)
    assert not result["workspaceOverflow"], (width, result)
    # The contained primary-navigation strip may scroll at tablet widths; the
    # workspace, entity toolbar and data surface must never escape the page.
    assert not result["tableFrameOverflow"], (width, result)
    assert not result["toolbarOverflow"], (width, result)
    assert result["primaryAreas"] == 5, result
    assert result["visibleEntityGroups"] == 1, result
    assert not result["permanentTestPanel"], result
    assert not result["permanentControlsPanel"], result


def main() -> None:
    output_dir = PROJECT_ROOT / ".artifacts" / "ai-configuration-workspace"
    output_dir.mkdir(parents=True, exist_ok=True)
    cookie = authenticated_session_cookie()

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
        page.on("pageerror", lambda error: print(f"PAGE ERROR: {error}"))
        page.on("console", lambda message: print(f"CONSOLE {message.type}: {message.text}") if message.type == "error" else None)
        page.on("response", lambda response: print(f"HTTP {response.status}: {response.url}") if response.status >= 400 else None)
        page.set_default_navigation_timeout(90_000)
        page.set_default_timeout(60_000)

        for width, height in VIEWPORTS:
            page.set_viewport_size({"width": width, "height": height})
            page.goto(BASE_URL, wait_until="domcontentloaded")
            page.wait_for_selector("[data-ai-workspace]", state="visible")
            page.wait_for_selector("#ia-resource-table tbody", state="attached")
            assert_layout(page, width)
            page.screenshot(
                path=str(output_dir / f"language-training-{width}x{height}.png"),
                animations="disabled",
            )

        page.set_viewport_size({"width": 1440, "height": 900})
        page.goto(BASE_URL, wait_until="domcontentloaded")
        page.wait_for_selector("[data-ai-workspace]", state="visible")
        for area, file_name in (
            ("semantic-model", "semantic-model.png"),
            ("query-response", "query-response.png"),
            ("business-governance", "business-governance.png"),
            ("test-diagnostics", "test-diagnostics.png"),
        ):
            page.locator(f'[data-ai-area="{area}"]').click()
            page.screenshot(path=str(output_dir / file_name), animations="disabled")

        page.locator("[data-ai-test-open]").first.click()
        page.wait_for_selector("[data-ai-test-drawer]:not([hidden])")
        page.screenshot(path=str(output_dir / "test-ai-drawer.png"), animations="disabled")
        page.locator("[data-ai-test-drawer] [data-ai-drawer-close]").last.click()

        page.locator("[data-ai-area='semantic-model']").click()
        page.locator("[data-ai-import-open]").click()
        page.wait_for_selector("[data-ai-import-drawer]:not([hidden])")
        page.screenshot(path=str(output_dir / "semantic-import-wizard.png"), animations="disabled")
        browser.close()

    print(f"PASS: AI Configuration screenshots written to {output_dir}")


if __name__ == "__main__":
    main()
