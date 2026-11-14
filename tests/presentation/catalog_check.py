"""Audit all original capture states using local native templates/fixtures.

Source coverage is reported separately: a local unavailable report is NOT a
validation of its Power BI contents. No save/sync/run/publish actions are used.
"""
import csv
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError
from browser_check import EDGE,OUT,geometry

BASE='http://127.0.0.1:8765'
ROOT=Path(__file__).resolve().parents[2]
CATALOG=ROOT.parents[1]/'exports/Mining360_Captures_2026-11-14/INDEX_PAGES.csv'


def select(page,selector,label=None):
    items=page.locator(selector)
    if label:
        matches=[items.nth(i) for i in range(items.count()) if items.nth(i).inner_text().strip().casefold()==label.casefold()]
        if not matches: return False
        item=matches[0]
    elif items.count(): item=items.first
    else:return False
    item.evaluate("e=>{const d=e.closest('details');if(d)d.open=true}")
    if not item.is_visible(): return False
    item.click(timeout=3000)
    page.wait_for_timeout(200)
    return True


def state(page,n,label):
    selectors={2:'[data-windows-start]',4:'[data-workspace-tab="turnover"]',
       5:'[data-workspace-tab="operations"]',7:'[data-workspace-tab="actions"]',
       27:'button[data-tab="integrations"]',28:'button[data-tab="parameters"]',
       29:'button[data-tab="database-configs"]',30:'button[data-tab="managed-tables"]',
       36:'[data-bm-tab="overview"]',37:'[data-bm-tab="conflicts"]',38:'[data-bm-tab="published"]',39:'[data-bm-tab="audit"]',
       55:'[data-open-add]',56:'[data-browser-select]',63:'[data-view="list"]',
       68:'[data-agent-view="router"]',69:'[data-agent-view="logs"]'}
    if n in selectors:return select(page,selectors[n])
    if n in (11,12,13,14,15):
        page.locator('[data-metric-selector]').select_option({11:'mtbs',12:'mtbf',13:'mttr',14:'fuel',15:'connectivity'}[n]);page.wait_for_timeout(350);return True
    if n==6:
        return select(page,'[data-workspace-tab="operations"]') and select(page,'[data-operation-tab="parts"]')
    if n==9:return select(page,'.pf-legend-item[data-open-cohort="current"]')
    if 40<=n<=54:return select(page,'#kb-tabs [data-resource-type]',label.split(' - ',1)[-1])
    if 64<=n<=67:return select(page,'button[data-ai-area]',label.split(' - ',1)[-1])
    if 83<=n<=87:
        if not select(page,'[data-report-list] button[data-report-id]'):return False
        if n>83:return select(page,'button[data-area]',label.split(' - ',1)[-1])
    return True


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--numbers',nargs='+',type=int);args=parser.parse_args()
    rows=[]; failures=[]
    output=OUT/'catalog';output.mkdir(exist_ok=True)
    with CATALOG.open(encoding='utf-8-sig') as f: original=list(csv.DictReader(f,delimiter=';'))
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=EDGE,headless=True)
        context=browser.new_context(viewport={'width':390,'height':844},extra_http_headers={'X-Presentation-Test':'responsive'},reduced_motion='reduce')
        context.route('**/*',lambda r:r.continue_() if r.request.url.startswith(BASE) or r.request.url.startswith(('data:','blob:')) else r.abort())
        for item in original:
            n=int(item['Numero']);label=item['Page ou vue'];path=item['Route']
            if args.numbers and n not in args.numbers:continue
            row={'number':n,'label':label,'route':path,'ui_status':'non testé','source_status':'fixture locale, production non retestée'}
            page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            try:
                response=page.goto(BASE+path,wait_until='load',timeout=10000)
                page.wait_for_timeout(250)
                row['http']=response.status
                if n==34:
                    row.update(ui_status='hors lot',source_status='Workflow absent du code de référence; 404 préexistante')
                elif response.status>=400:
                    row.update(ui_status='bloqué',source_status='Document ou données absents des fixtures locales')
                else:
                    ok=state(page,n,label)
                    row.update(ui_status='vérifié' if ok else 'bloqué',**geometry(page))
                    if not ok:row['source_status']='Sélection nécessaire absente des fixtures locales'
                    if item['Section']=='Power BI Reports':
                        row['source_status']='Cadre/état indisponible seulement; contenu et layouts Power BI non testés'
                    if n in (5,6,36,37,38,39):row['source_status']='Données de test; détail opérationnel ou Published Mapping réel non chargé'
                    if row.get('documentWidth',390)>391:failures.append(n)
                row['errors']=errors
                if n in (2,4,5,6,9,14,15,55,64,83,84,85,86,87):
                    page.screenshot(path=str(output/f'{n:03d}.png'),full_page=True)
            except Exception as exc:
                row.update(ui_status='bloqué',source_status=f'Contrôle incomplet: {type(exc).__name__}',error=str(exc).splitlines()[0][:180])
            finally:page.close()
            rows.append(row)
            if n%10==0:print(json.dumps({'catalog_completed':n}),flush=True)
        browser.close()
    name='catalog-retry.json' if args.numbers else 'catalog-results.json'
    (OUT/name).write_text(json.dumps(rows,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({'states':len(rows),'overflow_states':failures,'status_counts':{s:sum(r['ui_status']==s for r in rows) for s in ('vérifié','bloqué','non testé','hors lot')},'js_errors':sum(len(r.get('errors',[])) for r in rows)},ensure_ascii=False),flush=True)
