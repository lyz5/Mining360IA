"""Local browser acceptance. Test fixtures are visibly labelled, never product data."""
import json
import os
import sys
import threading
from pathlib import Path
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIServer, make_server, WSGIRequestHandler

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Mining360IA.settings')
os.environ['ENABLE_BUSINESS_REVIEW'] = 'Production'
os.environ['ENABLE_BUSINESS_COMMAND_CENTER'] = 'Production'
import django
django.setup()

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.handlers import StaticFilesHandler
from django.core.wsgi import get_wsgi_application
from django.test import Client
from playwright.sync_api import sync_playwright
from reports.parts_fulfillment_service import PartsFulfillmentService
from reports.test_parts_fulfillment import october
from unittest.mock import Mock
from urllib.parse import parse_qs, urlparse


class ThreadedServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


class QuietHandler(WSGIRequestHandler):
    def log_message(self, *args):
        pass


def main():
    out = ROOT / '.runlogs/parts-fulfillment'
    out.mkdir(parents=True, exist_ok=True)
    user = get_user_model().objects.filter(is_active=True, is_superuser=True).first()
    if not user:
        raise RuntimeError('No existing local administrator for browser validation.')
    client = Client()
    client.force_login(user)
    cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
    fixture_source = Mock()
    fixture_source.cached_query.return_value = [october(m) for m in ['2026-05','2026-06','2026-07','2026-08','2026-09','2026-10']]
    from datetime import date
    fixture = PartsFulfillmentService(user, source=fixture_source, today=date(2026,11,13)).summary('2026-10')
    server = make_server('127.0.0.1', 0, StaticFilesHandler(get_wsgi_application()), ThreadedServer, QuietHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f'http://127.0.0.1:{server.server_port}'
    errors = []
    requests = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')
            context = browser.new_context(viewport={'width':1440,'height':1100})
            context.add_cookies([{'name':settings.SESSION_COOKIE_NAME,'value':cookie,'domain':'127.0.0.1','path':'/','httpOnly':True,'secure':False}])
            page = context.new_page()
            page.on('pageerror', lambda e: errors.append(str(e)))
            mode = {'value':'fixture'}
            def summary(route):
                requests.append(route.request.url)
                if mode['value']=='error':
                    route.fulfill(status=503,json={'ready':False,'message':'Source unavailable (browser test fixture).'})
                elif mode['value']=='empty':
                    route.fulfill(json={'ready':True,'empty':True,'months':[],'series':[],'message':'No source data (browser test fixture).'})
                else:
                    requested=parse_qs(urlparse(route.request.url).query).get('month',['2026-10'])[0]
                    payload=fixture if requested==fixture['selected_month'] else PartsFulfillmentService(user,source=fixture_source,today=date(2026,11,13)).summary(requested)
                    route.fulfill(json=payload)
            page.route('**/api/business-review/parts-fulfillment/summary/**', summary)
            def details(route):
                requests.append(route.request.url)
                route.fulfill(json={'ready':True,'month':'2026-10','cohort':'Current Month','page':1,'pages':2,'total_rows':26,
                    'total':'8416346.36','control_total':'8416346.36','reconciliation':'reconciled',
                    'rows':[{'accounting_date':'2026-10-20','order_date':'2026-10-03','order_key':'000001|22|01',
                             'invoice_key':'22|22-01|000123','cohort':'Current Month','amount':'8416346.36'}]})
            page.route('**/api/business-review/parts-fulfillment/details/**', details)
            page.route('**/api/business-review/parts-fulfillment/export/**',lambda r:r.fulfill(body='Accounting Date,Order Key\n2026-10-20,000001|22|01\n',content_type='text/csv'))
            page.goto(url+'/business-review/parts-fulfillment/?month=2026-10')
            page.locator('[data-content]').wait_for(state='visible')
            assert page.locator('[data-month]').count()==1
            assert page.locator('[data-parts-fulfillment] select').count()==4 # month plus detail filters
            assert page.locator('[data-chart] svg').count()==1
            assert page.locator('[data-chart-orders]').count()==6
            assert page.locator('[data-chart-cohort]').count()==24 # zero Future Order omitted
            # Every month has one order column and one shared sales stack, in the
            # reference's bottom-to-top order: red, yellow, green.
            bars=page.locator('[data-chart]').evaluate('''node => {
                const sales=[...node.querySelectorAll('[data-chart-month="2026-10"]')];
                const byCohort=Object.fromEntries(sales.map(n=>[n.dataset.chartCohort,{x:+n.getAttribute('x'),y:+n.getAttribute('y'),h:+n.getAttribute('height')}]));
                const order=node.querySelector('[data-chart-orders="2026-10"]');
                return {cohorts:byCohort,orderX:+order.getAttribute('x'),orderWidth:+order.getAttribute('width')};
            }''')
            assert len({r['x'] for r in bars['cohorts'].values()})==1
            assert bars['orderX']+bars['orderWidth'] < bars['cohorts']['current']['x']
            assert bars['cohorts']['current']['y'] < bars['cohorts']['last']['y'] < bars['cohorts']['older']['y']
            assert bars['orderWidth']>50
            assert 'Value (M€)' in page.locator('[data-chart]').inner_text()
            assert 'Future Order' not in page.locator('[data-chart-legend]').inner_text()
            assert page.locator('[data-realization]').inner_text()=='N/A'
            assert page.locator('main').bounding_box()['x'] >= page.locator('.app-nav').bounding_box()['width']
            for month,bars in [('2026-08',4),('2026-09',5),('2026-10',6)]:
                page.locator('[data-month]').select_option(month)
                page.wait_for_function('(m) => document.querySelector("[data-month]").value===m && !document.querySelector("[data-month]").disabled',arg=month)
                assert page.locator('[data-chart-orders]').count()==bars
                assert month in page.url
            page.evaluate("""() => {const n=document.createElement('div');n.textContent='UI TEST FIXTURES — NOT LIVE SOURCE DATA';n.style.cssText='background:#fff3bf;color:#704900;padding:10px;text-align:center;font-weight:bold';document.querySelector('main').prepend(n)}""")
            page.screenshot(path=str(out/'desktop-fixtures.png'), full_page=True)
            page.locator('[data-chart-cohort="current"]').last.click()
            page.locator('[data-detail-rows] tr').wait_for()
            assert '000001|22|01' in page.locator('[data-detail-rows]').inner_text()
            assert 'reconciles' in page.locator('[data-detail-status]').inner_text()
            top_before=page.locator('[data-kpi="sales"]').inner_text()
            page.locator('[data-detail-cohort]').select_option('unallocated')
            page.wait_for_timeout(250)
            assert page.locator('[data-kpi="sales"]').inner_text()==top_before
            page.locator('[data-detail-search]').fill('000123')
            page.wait_for_timeout(550)
            assert any('search=000123' in r for r in requests)
            with page.expect_download() as download:
                page.locator('[data-export]').click()
            assert download.value.suggested_filename.startswith('parts-sales-')
            page.locator('[data-detail-close]').click()
            page.set_viewport_size({'width':390,'height':844})
            page.wait_for_timeout(350)
            page.evaluate('window.scrollTo(0,0)')
            page.screenshot(path=str(out/'mobile-fixtures.png'),full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth <= 390')
            negative=dict(fixture)
            negative['kpis']={**fixture['kpis'],'orders':'75','sales':'75','current':'100','last':'-30','older':'0','unallocated':'0','future':'5','reconciliation':{'status':'reconciled','label':'Reconciled','difference':'0'}}
            negative['series']=[negative['kpis']]
            original=fixture
            fixture=negative
            page.locator('[data-refresh]').click();page.locator('.pf-signed-table').wait_for()
            assert page.locator('[data-chart-cohort="last"]').evaluate('n => +n.getAttribute("y") >= +n.ownerSVGElement.querySelectorAll(".pf-axis-line")[1].getAttribute("y1")')
            assert 'Future Order' in page.locator('[data-chart-legend]').inner_text()
            fixture=original
            mode['value']='empty';page.locator('[data-refresh]').click();page.locator('[data-empty]').wait_for(state='visible')
            assert page.locator('[data-content]').is_hidden()
            assert 'No available month' in page.locator('[data-month]').inner_text()
            mode['value']='error';page.locator('[data-refresh]').click();page.locator('[data-error]').wait_for(state='visible')
            assert page.locator('[data-content]').is_hidden()
            assert 'Loading' not in page.locator('[data-month]').inner_text()
            mode['value']='fixture';page.locator('[data-retry]').click();page.locator('[data-content]').wait_for(state='visible')
            # Screenshot genuine source response if saved by the read-only command.
            live_file=ROOT/'.runlogs/parts_fulfillment_live.json'
            if live_file.exists():
                live=json.loads(live_file.read_text(encoding='utf-8'))
                page.unroute('**/api/business-review/parts-fulfillment/summary/**')
                page.route('**/api/business-review/parts-fulfillment/summary/**',lambda r:r.fulfill(status=200 if live.get('ready') else 503,json=live))
                page.set_viewport_size({'width':1440,'height':1100})
                page.wait_for_timeout(350)
                page.reload()
                page.locator('[data-content]' if live.get('ready') and not live.get('empty') else '[data-error]').wait_for(state='visible')
                if live.get('ready') and not live.get('empty'):
                    assert page.locator('[data-chart-orders]').count()==len(live['series'])
                    page.locator('.pf-trend').screenshot(path=str(out/'chart-source-response.png'))
                page.screenshot(path=str(out/'source-response.png'),full_page=True)
            browser.close()
        if errors:
            raise AssertionError(errors)
        print(json.dumps({'browser_checks':'passed','javascript_errors':errors,'screenshots':str(out)}))
    finally:
        client.session.flush()
        server.shutdown()


if __name__=='__main__':
    main()
