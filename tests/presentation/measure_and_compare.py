"""Repeated local lab timings and desktop geometry/pixel rollback comparisons."""
import json
import argparse
from pathlib import Path
from statistics import median
import time
from PIL import Image,ImageChops
from playwright.sync_api import sync_playwright
from browser_check import EDGE,OUT,ROUTES,geometry

BASE='http://127.0.0.1:8765'

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--pages',nargs='+');args=parser.parse_args()
    rows=[]; comparisons=[]
    folder=OUT/'comparison';folder.mkdir(exist_ok=True)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=EDGE,headless=True)
        for name in ('business','parts','excellence','reporting','chatbot','viewer','resources','report-config'):
            if args.pages and name not in args.pages:continue
            images={};boxes={}
            for variant in ('legacy','layout-only','responsive'):
                for trial in range(3):
                    context=browser.new_context(viewport={'width':1440,'height':900},reduced_motion='reduce',extra_http_headers={'X-Presentation-Test':variant})
                    context.route('**/*',lambda r:r.continue_() if r.request.url.startswith(BASE) or r.request.url.startswith(('data:','blob:')) else r.abort())
                    page=context.new_page()
                    page.add_init_script('''window.__uiMetrics={lcp:null,cls:0};
                      new PerformanceObserver(l=>{for(const e of l.getEntries())window.__uiMetrics.lcp=e.startTime}).observe({type:'largest-contentful-paint',buffered:true});
                      new PerformanceObserver(l=>{for(const e of l.getEntries())if(!e.hadRecentInput)window.__uiMetrics.cls+=e.value}).observe({type:'layout-shift',buffered:true});''')
                    start=time.perf_counter()
                    page.goto(BASE+ROUTES[name],wait_until='load')
                    loaded_ms=(time.perf_counter()-start)*1000
                    if name=='business':page.wait_for_selector('[data-content]:not([hidden])')
                    if name=='parts':page.wait_for_selector('[data-chart] svg')
                    if name=='excellence':page.wait_for_function('document.querySelector("[data-availability-value]").textContent.includes("86.42")')
                    ready_ms=(time.perf_counter()-start)*1000
                    # Capture after the existing loading/opacity transitions;
                    # readiness timing above is measured before this settle wait.
                    page.wait_for_timeout(500)
                    metric=page.evaluate('window.__uiMetrics')
                    rows.append({'page':name,'variant':variant,'trial':trial+1,'load_ms':round(loaded_ms,2),'ready_ms':round(ready_ms,2),**metric})
                    if trial==2:
                        path=folder/f'{name}-{variant}-1440.png'
                        page.screenshot(path=str(path),full_page=True,animations='disabled')
                        images[variant]=path
                        boxes[variant]=geometry(page)['boxes']
                    context.close()
            a=Image.open(images['legacy']).convert('RGB');b=Image.open(images['layout-only']).convert('RGB')
            bbox=ImageChops.difference(a,b).getbbox() if a.size==b.size else 'image dimensions differ'
            comparisons.append({'page':name,'layout_only_geometry_equal':boxes['legacy']==boxes['layout-only'],
                'theme_geometry_equal':boxes['legacy']==boxes['responsive'],'pixel_difference_bbox':bbox})
            print(json.dumps({'compared':name,**comparisons[-1]}),flush=True)
        browser.close()
    medians=[]
    for name in dict.fromkeys(r['page'] for r in rows):
        for variant in ('legacy','layout-only','responsive'):
            selected=[r for r in rows if r['page']==name and r['variant']==variant]
            medians.append({'page':name,'variant':variant,'samples':3,
                **{key:round(median(r[key] for r in selected if r[key] is not None),2) for key in ('load_ms','ready_ms','lcp','cls') if any(r[key] is not None for r in selected)}})
    result={'method':'Local Windows Edge; fresh browser context per trial, same fixture database and warmed local backend; 3 samples. No CPU/network throttling. Not field p75 or live Power BI timing.',
            'comparisons':comparisons,'medians':medians,'samples':rows,'inp':'Not measured; no field traffic sample.'}
    target='measurements-retry.json' if args.pages else 'measurements.json'
    (OUT/target).write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'desktop_comparisons':len(comparisons),'samples':len(rows),'layout_regressions':[r for r in comparisons if not r['layout_only_geometry_equal']]}),flush=True)
