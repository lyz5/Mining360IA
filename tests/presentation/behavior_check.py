"""Loaded, signed, empty, error, concurrency, keyboard and export UI scenarios."""
import json
from urllib.parse import urlparse,parse_qs
from playwright.sync_api import sync_playwright
from browser_check import EDGE,OUT

BASE='http://127.0.0.1:8765'


def run():
    checks=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=EDGE,headless=True)
        context=browser.new_context(viewport={'width':390,'height':844},reduced_motion='reduce',
            extra_http_headers={'X-Presentation-Test':'responsive'},accept_downloads=True)
        context.route('**/*',lambda r:r.continue_() if r.request.url.startswith(BASE) or r.request.url.startswith(('blob:','data:')) else r.abort())
        page=context.new_page()
        # Both desktop sidebar preferences must yield a fully legible More menu.
        for preference in ('0','1'):
            page.goto(BASE+'/business-review/command-center/')
            page.evaluate('(v)=>localStorage.setItem("mining360ia.navCollapsed",v)',preference)
            page.reload()
            page.wait_for_selector('[data-content]:not([hidden])')
            page.get_by_role('button',name='More',exact=True).click()
            assert page.locator('.app-nav').bounding_box()['width']>300
            assert page.locator('.app-nav a',has_text='Resources').is_visible()
            page.keyboard.press('Escape')
            page.set_viewport_size({'width':1440,'height':900})
            assert page.locator('body').evaluate('(e)=>e.classList.contains("nav-collapsed")')==(preference=='1')
            page.set_viewport_size({'width':390,'height':844})
        checks.append('More legible with both sidebar preferences; preference restored after resize')
        # All five categories stay in the paired-column chart and controls.
        page.goto(BASE+'/business-review/parts-fulfillment/')
        page.wait_for_selector('[data-chart] svg')
        assert page.locator('.pf-chart rect[role="button"]').count()>=8
        assert page.locator('[data-kpi="sales"]').inner_text()!='—'
        page.locator('.pf-legend-item[data-open-cohort="unallocated"]').click()
        page.wait_for_selector('[data-detail-rows] tr')
        assert 'TEST|TEST-01|000004' in page.locator('[data-detail-rows]').inner_text()
        assert page.locator('[data-detail-rows]').inner_text().find('Unallocated')>=0
        checks.append('Parts loaded measures, paired columns, Unallocated rows without an order, textual invoice key')
        page.locator('[data-month]').select_option('2026-09')
        page.wait_for_selector('.pf-signed-table')
        assert 'Future Order' in page.locator('.pf-signed-table').inner_text()
        assert '-' in page.locator('.pf-signed-table').inner_text()
        page.locator('.pf-legend-item[data-open-cohort="future"]').click()
        page.wait_for_selector('[data-detail-rows] tr')
        cells=page.locator('[data-detail-rows] tr').first.locator('td')
        assert cells.nth(0).inner_text()!=cells.nth(1).inner_text()
        checks.append('Future Order detail exposes distinct accounting and following-month order dates')
        checks.append('Signed credits use a table; Future Order stays in data/control rather than disappearing')
        page.locator('[data-month]').select_option('2026-08')
        page.wait_for_selector('[data-empty]:not([hidden])')
        assert not page.locator('[data-content]').is_visible()
        checks.append('Empty source month distinguished from zero and unavailable')
        page.locator('[data-month]').select_option('2026-10')
        page.wait_for_selector('[data-chart] svg')
        page.evaluate('Object.defineProperty(navigator,"clipboard",{value:undefined,configurable:true})')
        page.locator('[data-pf-copy="New_Orders"]').click()
        with page.expect_download(timeout=30000) as download:
            page.get_by_role('button',name='Download PNG',exact=True).click()
        download.value.save_as(str(OUT/'parts-copy-fallback.png'))
        assert (OUT/'parts-copy-fallback.png').stat().st_size>1000
        checks.append('Existing Copy visual keeps its actual PNG download fallback')
        # In-flight/failed metric context must not relabel an earlier result.
        page.goto(BASE+'/excellence-center/')
        page.wait_for_function('document.querySelector("[data-availability-value]").textContent.includes("86.42")')
        page.route('**/api/home/availability-command-center/**', lambda route:
            route.fulfill(status=503,json={'ok':False,'error':'UI fixture: selected metric unavailable'})
            if 'metric=mtbs' in route.request.url else route.continue_())
        page.locator('[data-metric-selector]').select_option('mtbs')
        page.wait_for_selector('[data-homepage-error]:not([hidden])')
        assert 'MTBS' in page.locator('[data-center-title]').inner_text()
        assert not page.locator('[data-availability-value]').is_visible()
        checks.append('Failed MTBS displays its own context and hides earlier Availability results')
        page.unroute('**/api/home/availability-command-center/**')
        payloads={m:context.request.get(BASE+f'/api/home/availability-command-center/?metric={m}').json() for m in ('availability','mtbs','mtbf')}
        page.add_init_script('''((payloads)=>{
          const original=window.fetch;
          window.fetch=(url,options)=>{
            const parsed=new URL(url,location.href),metric=parsed.searchParams.get('metric');
            if(parsed.pathname==='/api/home/availability-command-center/' && payloads[metric])
              return new Promise(resolve=>setTimeout(()=>resolve(new Response(JSON.stringify(payloads[metric]),{status:200,headers:{'Content-Type':'application/json'}})),metric==='mtbs'?350:30));
            return original(url,options);
          };
        })('''+json.dumps(payloads)+');')
        page.goto(BASE+'/excellence-center/')
        page.wait_for_function('document.querySelector("[data-availability-value]").textContent.includes("86.42")')
        page.evaluate('''()=>{const s=document.querySelector('[data-metric-selector]');s.value='mtbs';s.dispatchEvent(new Event('change'));setTimeout(()=>{s.value='mtbf';s.dispatchEvent(new Event('change'));},5)}''')
        page.wait_for_timeout(500)
        assert 'MTBF' in page.locator('[data-center-title]').inner_text()
        assert '64.50' in page.locator('[data-availability-value]').inner_text()
        assert page.locator('[data-availability-value]').is_visible()
        checks.append('Late aborted MTBS response cannot replace newer MTBF result or loading state')
        # The input is the same DOM node through layout/keyboard/history changes.
        page.goto(BASE+'/codex-chatbot/')
        question=page.locator('#codex-question')
        question.fill('Unsent UI test draft')
        assert not page.locator('.m360-bottom-nav').is_visible()
        page.set_viewport_size({'width':390,'height':500})
        assert question.input_value()=='Unsent UI test draft'
        assert page.locator('#codex-composer button[type="submit"]').bounding_box()['y']<500
        page.locator('#codex-history-toggle').click()
        assert page.locator('.codex-chat__history').is_visible()
        page.wait_for_selector('.codex-chat__history[role="dialog"]')
        page.keyboard.press('Escape')
        assert not page.locator('.codex-chat__history').is_visible()
        assert question.input_value()=='Unsent UI test draft'
        page.set_viewport_size({'width':1440,'height':900})
        page.set_viewport_size({'width':390,'height':844})
        assert question.input_value()=='Unsent UI test draft'
        checks.append('Chat draft survives keyboard-size emulation, history Escape and desktop/mobile cycle')
        browser.close()
    (OUT/'behavior-results.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
    print(json.dumps({'passed':len(checks),'checks':checks}),flush=True)


if __name__=='__main__':run()
