"""Local login presentation check. No real directory login or account change."""
import json, os, sys, threading
from pathlib import Path
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIServer, make_server, WSGIRequestHandler
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','Mining360IA.settings')
import django;django.setup()
from django.contrib.staticfiles.handlers import StaticFilesHandler
from django.core.wsgi import get_wsgi_application
from playwright.sync_api import sync_playwright

class ThreadedServer(ThreadingMixIn,WSGIServer):daemon_threads=True
class QuietHandler(WSGIRequestHandler):
    def log_message(self,*args):pass

def main():
    out=ROOT/'.runlogs/login-premium';out.mkdir(parents=True,exist_ok=True)
    errors=[];checks={}
    server=make_server('127.0.0.1',0,StaticFilesHandler(get_wsgi_application()),ThreadedServer,QuietHandler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    url=f'http://127.0.0.1:{server.server_port}/login/?next=/business-review/parts-fulfillment/'
    try:
        with patch('reports.views.active_directory_login_enabled',return_value=True) as ad, patch('reports.views.authenticate',return_value=None) as authenticate, sync_playwright() as p:
            browser=p.chromium.launch(headless=True,executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')
            context=browser.new_context(viewport={'width':1672,'height':941})
            page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
            response=page.goto(url);assert response.status==200
            page.locator('[data-windows-start]').wait_for(state='visible')
            page.wait_for_function('document.querySelector(".login-scene-image").complete && document.querySelector(".login-scene-image").naturalWidth>0')
            page.wait_for_timeout(1700)
            assert page.locator('input[name=csrfmiddlewaretoken]').input_value()
            assert page.locator('input[name=next]').input_value()=='/business-review/parts-fulfillment/'
            assert page.locator('[data-windows-form]').is_hidden()
            page.screenshot(path=str(out/'login-desktop.png'),full_page=True)
            checks['desktop']='passed'
            page.keyboard.press('Tab');assert page.locator('[data-windows-start]').evaluate('n=>n===document.activeElement')
            page.keyboard.press('Enter');page.locator('[data-windows-form]').wait_for(state='visible')
            assert page.locator('[data-windows-start]').is_hidden()
            username=page.locator('input[name=username]');password=page.locator('input[name=password]')
            username.fill('NEEMBA\\ui-preview');password.fill('preview-only-not-a-real-password')
            page.locator('[data-password-toggle]').click();assert password.get_attribute('type')=='text'
            page.locator('[data-password-toggle]').click();assert password.get_attribute('type')=='password'
            page.screenshot(path=str(out/'login-credentials.png'),full_page=True)
            page.locator('[data-windows-form] button[type=submit]').click()
            page.locator('.login-messages').wait_for(state='visible')
            assert 'Invalid username or password' in page.locator('.login-messages').inner_text()
            assert page.locator('[data-windows-form]').is_visible()
            assert password.input_value()==''
            assert authenticate.called
            page.screenshot(path=str(out/'login-error.png'),full_page=True)
            checks['form_csrf_keyboard_password_and_error']='passed (mocked authentication)'
            mobile=browser.new_context(viewport={'width':390,'height':844},reduced_motion='reduce')
            mobile_page=mobile.new_page();mobile_page.on('pageerror',lambda e:errors.append(str(e)))
            mobile_page.goto(url);mobile_page.locator('[data-windows-start]').wait_for(state='visible')
            mobile_page.wait_for_function('document.querySelector(".login-scene-image").complete')
            assert mobile_page.evaluate('document.documentElement.scrollWidth<=390')
            assert mobile_page.locator('.login-panel').evaluate('n=>getComputedStyle(n).animationName')=='none'
            mobile_page.screenshot(path=str(out/'login-mobile.png'),full_page=True)
            mobile_page.locator('[data-windows-start]').click()
            assert mobile_page.locator('[data-windows-form]').is_visible()
            assert mobile_page.evaluate('document.documentElement.scrollWidth<=390')
            checks['mobile_and_reduced_motion']='passed'
            nojs=browser.new_context(java_script_enabled=False,viewport={'width':1440,'height':900})
            nojs_page=nojs.new_page();nojs_page.goto(url)
            assert nojs_page.locator('[data-windows-form]').is_visible()
            assert nojs_page.locator('[data-windows-start]').is_hidden()
            checks['no_javascript_form']='passed'
            ad.return_value=False
            fallback=browser.new_page(viewport={'width':1440,'height':900});fallback.goto(url)
            assert fallback.locator('input[name=username]').is_visible()
            assert fallback.get_by_role('link',name='Continue with Microsoft').count()==1
            checks['local_and_microsoft_fallback']='passed'
            browser.close()
        assert not errors,errors
        result={'checks':checks,'javascript_errors':errors,'screenshots':str(out)}
        (out/'browser-results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result),flush=True)
    finally:server.shutdown()

if __name__=='__main__':main()
