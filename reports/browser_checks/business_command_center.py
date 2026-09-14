"""Responsive interaction and visual checks for Business Command Center."""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from wsgiref.simple_server import make_server

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Mining360IA.settings")
os.environ["ENABLE_BUSINESS_COMMAND_CENTER"] = "Production"
os.environ["ENABLE_BUSINESS_COMMAND_CENTER_CUSTOMERS"] = "Production"
os.environ["ENABLE_BUSINESS_COMMAND_CENTER_COUNTRIES"] = "Production"
os.environ["ENABLE_BUSINESS_COMMAND_CENTER_KEY_ACCOUNTS"] = "Production"
os.environ["ENABLE_BUSINESS_COMMAND_CENTER_LAST_VISIT"] = "Production"
os.environ["ENABLE_BUSINESS_COMMAND_CENTER_ATTENTION"] = "Production"
os.environ["ENABLE_BUSINESS_COMMAND_CENTER_WATCHLIST"] = "Production"
os.environ["ENABLE_BUSINESS_COMMAND_CENTER_PRESENTATION_MODE"] = "Production"

import django
django.setup()

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.handlers import StaticFilesHandler
from django.core.wsgi import get_wsgi_application
from django.test import Client
from playwright.sync_api import sync_playwright


def session_cookie():
    user = get_user_model().objects.filter(is_superuser=True, is_active=True).first()
    client = Client(); client.force_login(user)
    return client.cookies[settings.SESSION_COOKIE_NAME].value


def payload():
    lines = [
        {"code":"machine","label":"Machine","revenue":169769627.46,"comparison_revenue":158000000,"absolute_delta":11769627.46,"relative_delta":7.4,"share":44.9,"rank":2},
        {"code":"parts","label":"Parts","revenue":177176641.25,"comparison_revenue":156000000,"absolute_delta":21176641.25,"relative_delta":13.6,"share":46.9,"rank":1},
        {"code":"service","label":"Service","revenue":17674680.64,"comparison_revenue":22000000,"absolute_delta":-4325319.36,"relative_delta":-19.7,"share":4.7,"rank":3},
        {"code":"rental","label":"Rental","revenue":13262293.53,"comparison_revenue":13500000,"absolute_delta":-237706.47,"relative_delta":-1.8,"share":3.5,"rank":4},
        {"code":"unclassified","label":"Unclassified","revenue":0,"comparison_revenue":0,"absolute_delta":0,"relative_delta":None,"share":0,"rank":5},
    ]
    entities = [
        {"id":"a1","name":"SNIM","rank":1,"revenue":53000000,"previous_revenue":47000000,"absolute_delta":6000000,"relative_delta":12.8,"share":14.0,"country":"Mauritania","key_account":"SNIM Group","business_line_mix":{"machine":18000000,"parts":27000000,"service":5000000,"rental":3000000,"unclassified":0}},
        {"id":"a2","name":"B2Gold Fekola","rank":2,"revenue":42800000,"previous_revenue":41000000,"absolute_delta":1800000,"relative_delta":4.4,"share":11.3,"country":"Mali","key_account":"B2Gold","business_line_mix":{"machine":17000000,"parts":20000000,"service":4000000,"rental":1800000,"unclassified":0}},
        {"id":"a3","name":"Kiaka SA","rank":3,"revenue":16710048,"previous_revenue":12000000,"absolute_delta":4710048,"relative_delta":39.3,"share":4.4,"country":"Burkina Faso","key_account":None,"business_line_mix":{"machine":9000000,"parts":6000000,"service":1210048,"rental":500000,"unclassified":0}},
    ]
    return {
        "ready":True,"mapping_ready":True,"mode":"published","snapshot_id":None,
        "context":{"period":"ytd","period_label":"YTD 2026","start_date":"2026-01-01","end_date":"2026-09-08","comparison":"same_period_last_year","comparison_label":"Same period 2025","business_line":"all_business","currency":"EUR","published_mapping_version":4},
        "freshness":{"data_through_date":"2026-09-08","source_snapshot_at":"2026-09-10T08:30:00Z","snapshot_id":"sync-1"},
        "confidence":{"status":"Moderate","customer_coverage":82.4,"country_coverage":79.1,"key_account_coverage":54.3,"unallocated_revenue":50400000,"unclassified_revenue":0,"warnings":["Customer rankings cover 82.4% of Revenue."]},
        "hero":{"revenue":377883242.89,"comparison_revenue":349500000,"absolute_delta":28383242.89,"relative_delta":8.1,"top_contributor":"Parts"},
        "business_lines":lines,
        "changes":[{"entity_id":"parts","entity":"Parts","current_value":177176641.25,"comparison_value":156000000,"absolute_delta":21176641.25,"relative_delta":13.6},{"entity_id":"service","entity":"Service","current_value":17674680.64,"comparison_value":22000000,"absolute_delta":-4325319.36,"relative_delta":-19.7}],
        "since_last_visit":{"filter_hash":"abc","previous_visit_at":"2026-09-10T06:00:00Z","items":[{"title":"Revenue changed since your last visit","absolute_delta":420000}]},
        "trend":[{"date":f"2026-{month:02d}-01","value":value} for month,value in enumerate([38,42,47,39,50,46,48,55,13],1)],
        "comparison_trend":[{"date":f"2025-{month:02d}-01","value":value} for month,value in enumerate([34,39,41,40,45,44,46,47,12],1)],
        "mix":lines,"bridge":[{"code":item["code"],"label":item["label"],"delta":item["absolute_delta"]} for item in lines],
        "dimensions":{"customers":entities,"countries":[{**entities[0],"id":"MR","name":"Mauritania"},{**entities[1],"id":"ML","name":"Mali"}],"key_accounts":[{**entities[1],"id":"K1","name":"B2Gold"}]},
        "sales_review":{
            "summary":{"actual_revenue":377883242.89,"comparison_revenue":349500000,"absolute_delta":28383242.89,"relative_delta":8.1},
            "by_business_line":lines,
            "by_country":[{**entities[0],"id":"MR","name":"Mauritania"},{**entities[1],"id":"ML","name":"Mali"}],
            "by_customer":entities,
            "concentration":{"top_1_share":14,"top_5_share":41,"top_10_share":63},
            "budget":{"status":"NOT_AVAILABLE","message":"A certified Mining Sales budget source is not configured yet."},
            "firm_orders":{"status":"NOT_AVAILABLE","message":"Firm Orders and Sales Funnel require a governed structured source."},
        },
        "filter_options":{"customers":[{"id":x["id"],"name":x["name"]} for x in entities],"countries":[{"id":"MR","name":"Mauritania"},{"id":"ML","name":"Mali"}],"key_accounts":[{"id":"K1","name":"B2Gold"}]},
        "attention_items":[{"code":"BUSINESS_LINE_DECLINE","severity":"High","title":"Service Revenue declined","entity":"Service","impact":4325319.36},{"code":"UNALLOCATED_REVENUE","severity":"High","title":"Revenue is not assigned to published Customers","entity":"Mapping coverage","impact":50400000}],
        "concentration":{"top_1_share":14,"top_5_share":41,"top_10_share":63},"reconciliation":{"status":"RECONCILED","difference":0,"tolerance":0.01},
        "actions_summary":{"open":8,"critical":2,"overdue":1},"watchlist":[{"id":"w1","entity_type":"Customer","entity_id":"a1","display_name":"SNIM"}],
    }


def main():
    output = PROJECT_ROOT / ".artifacts" / "business-command-center"; output.mkdir(parents=True, exist_ok=True)
    cookie_value = session_cookie()
    server = make_server("127.0.0.1", 8124, StaticFilesHandler(get_wsgi_application()))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
            context = browser.new_context()
            context.add_cookies([{"name":settings.SESSION_COOKIE_NAME,"value":cookie_value,"domain":"127.0.0.1","path":"/","httpOnly":True,"sameSite":"Lax"}])
            page = context.new_page(); errors=[]; page.on("pageerror",lambda error:errors.append(str(error)))
            page.route("**/api/business-review/command-center/bootstrap/**",lambda route:route.fulfill(json=payload()))
            for width,height,name in ((1440,900,"desktop"),(1280,800,"compact-desktop"),(1100,800,"laptop"),(768,1024,"tablet"),(390,844,"mobile")):
                page.set_viewport_size({"width":width,"height":height}); page.goto("http://127.0.0.1:8124/business-review/command-center/",wait_until="networkidle")
                page.wait_for_selector('[data-content]:visible'); checks=page.evaluate("""() => {const doc=document.documentElement;const offenders=[...document.querySelectorAll('body *')].filter(el=>{const r=el.getBoundingClientRect();return r.right>doc.clientWidth+1||r.left<-1}).slice(0,8).map(el=>({tag:el.tagName,cls:el.className,right:Math.round(el.getBoundingClientRect().right),width:Math.round(el.getBoundingClientRect().width)}));return {overflow:doc.scrollWidth>doc.clientWidth+1,offenders,hero:document.querySelector('[data-hero-value]')?.textContent,cards:document.querySelectorAll('[data-line]').length,salesRows:document.querySelectorAll('[data-sales-body] tr').length,partsRows:document.querySelectorAll('[data-parts-body] tr').length,technical:Boolean(document.querySelector('[data-bm-sync],[data-bm-confirm]'))}}""")
                if checks["overflow"] or checks["cards"] != 4 or checks["salesRows"] != 4 or checks["partsRows"] < 1 or checks["technical"] or "377.9M" not in checks["hero"]: raise AssertionError(f"{name}: {checks}")
                page.screenshot(path=str(output/f"command-center-{name}.png"),full_page=True)
                if name=="desktop":
                    page.locator('[data-line="parts"]').click(); page.wait_for_timeout(250)
                    page.locator('[data-entity-id="a1"]').click(); page.wait_for_selector('[data-drawer]:visible')
                    page.screenshot(path=str(output/"command-center-customer-drawer.png"),full_page=True); page.locator('[data-drawer-close]').click()
                print(f"PASS {name}: {checks}")
            if errors: raise AssertionError(errors)
            browser.close()
    finally:
        server.shutdown(); server.server_close()


if __name__ == "__main__": main()
