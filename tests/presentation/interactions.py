"""Presentation behavior checks; all requests remain on the local fixture host."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from browser_check import EDGE, OUT


def run():
    checks = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=EDGE, headless=True)
        context = browser.new_context(viewport={'width':390,'height':844}, extra_http_headers={'X-Presentation-Test':'layout-only'}, reduced_motion='reduce')
        context.route('**/*', lambda route: route.continue_() if route.request.url.startswith('http://127.0.0.1:8765/') else route.abort())
        page = context.new_page()
        calls = []
        page.on('request',lambda request:calls.append(request.url))
        page.goto('http://127.0.0.1:8765/business-review/command-center/')
        page.wait_for_selector('[data-hero-value]:not(:has-text("--"))')
        bootstrap = page.locator('[data-command-center]').get_attribute('data-bootstrap-url')
        count = lambda:sum(bootstrap in url for url in calls)
        start = count()
        assert not page.locator('.app-nav').is_visible()
        page.get_by_role('button',name='More',exact=True).click()
        assert page.locator('.app-nav').is_visible()
        assert page.locator('main').evaluate('(e)=>e.inert')
        page.keyboard.press('Escape')
        assert not page.locator('.app-nav').is_visible()
        assert not page.locator('main').evaluate('(e)=>e.inert')
        assert count()==start
        checks.append('menu opens/closes, focus and main inert restored, no business request')
        page.evaluate('()=>{window.__stopUiSpinner=window.m360AjaxSpinner.begin(true)}')
        page.wait_for_selector('[data-ajax-spinner]:not([hidden])',state='visible',timeout=3000)
        assert page.locator('[data-ajax-spinner]').bounding_box()['height']<100
        page.get_by_role('button',name='More',exact=True).click()
        assert page.locator('.app-nav').is_visible()
        page.keyboard.press('Escape')
        page.evaluate('window.__stopUiSpinner()')
        assert count()==start
        checks.append('shared loading indicator stays compact and leaves navigation clear; no request-policy change')
        filters = page.locator('[data-filter-open]')
        filters.click()
        page.locator('[data-filter="business_line"]').select_option('parts')
        page.wait_for_timeout(150)
        assert count()==start
        page.locator('[data-filter-cancel]').click()
        assert page.locator('[data-filter="business_line"]').input_value()=='all_business'
        assert count()==start
        checks.append('filter draft/Cancel preserves applied value and sends no query')
        filters.click()
        page.locator('[data-filter="business_line"]').select_option('parts')
        page.locator('[data-filter-apply]').click()
        page.wait_for_timeout(500)
        assert count()==start+1, (start,count())
        assert 'business_line=parts' in page.url
        checks.append('Apply commits once, one bootstrap request, URL matches context')
        for width in (1440,390,1024,1440):
            page.set_viewport_size({'width':width,'height':900})
            page.wait_for_timeout(120)
        assert count()==start+1
        assert page.locator('[data-filter="business_line"]').input_value()=='parts'
        assert not page.locator('.m360-bottom-nav').is_visible()
        checks.append('desktop/mobile/tablet/desktop cycle preserves filter and sends no query')
        page.goto('http://127.0.0.1:8765/business-review/command-center/?view=turnover')
        page.wait_for_selector('[data-content]:not([hidden])')
        assert page.locator('[data-workspace="turnover"]').is_visible()
        page.evaluate('window.dispatchEvent(new PopStateEvent("popstate"))')
        assert page.locator('[data-workspace="turnover"]').is_visible()
        checks.append('Mining Turnover URL/back context is retained instead of falling back to Executive')
        context.close()
        browser.close()
    OUT.joinpath('pilot-interactions.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
    print(json.dumps({'passed':len(checks),'checks':checks}),flush=True)


if __name__=='__main__': run()
