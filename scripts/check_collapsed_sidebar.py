"""Capture and validate the collapsed application navigation rail."""

from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import Client
from playwright.sync_api import sync_playwright


def main():
    user = get_user_model().objects.filter(is_superuser=True, is_active=True).first()
    if user is None:
        raise RuntimeError("An active superuser is required.")

    client = Client()
    client.force_login(user)
    session_id = client.cookies["sessionid"].value
    output = Path("artifacts/collapsed-sidebar-1366x768.png")
    output.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        )
        context = browser.new_context(
            base_url="http://127.0.0.1:8001",
            viewport={"width": 1366, "height": 768},
        )
        context.add_cookies([{
            "name": "sessionid",
            "value": session_id,
            "domain": "127.0.0.1",
            "path": "/",
            "httpOnly": True,
            "sameSite": "Lax",
        }])
        page = context.new_page()
        page.add_init_script("localStorage.setItem('mining360ia.navCollapsed', '1')")
        page.goto("/reporting/", wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_selector("body.nav-collapsed")
        page.wait_for_timeout(500)
        metrics = page.evaluate("""() => {
            const toggle = document.querySelector('.nav-toggle').getBoundingClientRect();
            const items = [...document.querySelectorAll(
                '.nav-links > a, .nav-links > .nav-group > .nav-group-label'
            )].map(element => element.getBoundingClientRect());
            return {
                toggleGap: items[0].top - toggle.bottom,
                itemGaps: items.slice(1).map((rect, index) => rect.top - items[index].bottom),
                sizes: items.map(rect => [rect.width, rect.height]),
                overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
            };
        }""")
        page.screenshot(path=str(output))
        browser.close()

    assert metrics["toggleGap"] >= 10, metrics
    assert all(gap >= 8 for gap in metrics["itemGaps"]), metrics
    assert all(width >= 48 and height >= 48 for width, height in metrics["sizes"]), metrics
    assert metrics["overflow"] is False, metrics
    print(metrics)
    print(output)


if __name__ == "__main__":
    main()
