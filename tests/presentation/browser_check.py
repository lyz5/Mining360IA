"""Repeatable Edge UI checks against fixture_server.py, never production."""
import argparse
import hashlib
import json
from pathlib import Path
import time
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / '.ui-test-artifacts'
EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
ROUTES = {
    'business': '/business-review/command-center/',
    'parts': '/business-review/parts-fulfillment/',
    'excellence': '/excellence-center/',
    'reporting': '/reporting/',
    'chatbot': '/codex-chatbot/',
    'resources': '/resources/',
    'users': '/users/',
    'data': '/data/',
    'knowledge': '/knowledge-base/',
    'ai-config': '/ia-config/',
    'system-config': '/system-config/',
    'report-config': '/config/reporting/',
    'login': '/login/',
    'viewer': '/reporting/reports/00000000-0000-4000-8000-000000000001/',
    'sources':'/data-sources/',
    'source-detail':'/data-sources/ui-test/',
    'agents':'/ia-config/agents/',
    'mapping':'/config/business-mapping/',
    'invoices':'/invoice-tracking/',
    'deployment':'/config/deployment/',
    'downtime':'/config/downtime-checking/',
    'resource-admin':'/resources/knowledge/',
}


def geometry(page):
    return page.evaluate('''() => ({width:document.documentElement.clientWidth,
      documentWidth:document.documentElement.scrollWidth,
      boxes:[...document.querySelectorAll('.app-shell,.bcc-header,.bcc-hero,.bcc-line-grid,.bcc-panel,.pf-header,.codex-composer')]
       .filter(e=>e.getClientRects().length).map(e=>{let r=e.getBoundingClientRect();return {cls:e.className,x:r.x,y:r.y,w:r.width,h:r.height}}),
      overflow:[...document.querySelectorAll('main *')].filter(e=>{let r=e.getBoundingClientRect();return r.right>innerWidth+1&&r.width>0&&getComputedStyle(e).position!=='fixed'&&!e.closest('.pf-chart-scroll,.pf-table-scroll,.m360-table-scroll,[hidden]')}).slice(0,12).map(e=>e.className||e.tagName)})''')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--variant', choices=['legacy','responsive','layout-only'], default='responsive')
    parser.add_argument('--pilot', action='store_true')
    parser.add_argument('--pages', nargs='+')
    parser.add_argument('--widths', nargs='+',type=int)
    args = parser.parse_args()
    rows = []
    out = OUT / args.variant
    out.mkdir(exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=EDGE, headless=True)
        context = browser.new_context(extra_http_headers={'X-Presentation-Test': args.variant}, reduced_motion='reduce')
        context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(('http://127.0.0.1:8765/','data:','blob:')) else route.abort())
        selected=dict(business=ROUTES['business']) if args.pilot else {k:v for k,v in ROUTES.items() if not args.pages or k in args.pages}
        for name, path in selected.items():
            for width in (args.widths or ([390,1024,1440] if args.variant=='legacy' else [320,360,390,430,767,768,769,1024,1199,1200,1201,1280,1366,1440,1920])):
                page = context.new_page()
                page.set_viewport_size({'width':width,'height':844 if width<768 else 768 if width==1366 else 900})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                start = time.perf_counter()
                response = page.goto('http://127.0.0.1:8765'+path, wait_until='load', timeout=30000)
                page.wait_for_timeout(600)
                row = {'page':name,'width':width,'http':response.status,'load_ms':round((time.perf_counter()-start)*1000), 'errors':errors,**geometry(page)}
                if width in (390,1024,1440):
                    page.screenshot(path=str(out/f'{name}-{width}.png'), full_page=True, animations='disabled')
                rows.append(row)
                page.close()
            print(json.dumps({'page_complete':name}),flush=True)
        browser.close()
    result_name='results'+('-'+'-'.join(args.pages) if args.pages else '')+'.json'
    (out/result_name).write_text(json.dumps(rows,indent=2),encoding='utf-8')
    print(json.dumps({'views':len(rows),'overflows':[{k:r[k] for k in ('page','width','documentWidth','overflow')} for r in rows if r['documentWidth']>r['width']+1], 'errors':[r for r in rows if r['errors']]}),flush=True)
