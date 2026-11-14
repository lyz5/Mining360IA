"""Local, isolated UI fixture host. Never imported by the application.

Uses the real routes/templates and a fresh SQLite test database. External source
access and all browser mutations are blocked. No production credentials/data.
"""
import argparse
import json
import mimetypes
import os
from pathlib import Path
import sys
import logging
from threading import RLock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from contextlib import ExitStack

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUT = ROOT / '.ui-test-artifacts'
OUT.mkdir(exist_ok=True)
os.environ.update(DJANGO_SETTINGS_MODULE='Mining360IA.settings', MINING360_DEBUG='1',
                  MINING360_DATABASE_ENGINE='sqlite', MINING360_SQLITE_PATH=str(OUT / 'fixtures.sqlite3'),
                  BUSINESS_REVENUE_AUTO_SYNC='false', BUSINESS_MAPPING_AUTO_SYNC_ON_STUDIO_OPEN='false',
                  MINING360_SQL_CONFIG_STORE='0')
import django
django.setup()
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.staticfiles import finders
from django.core.management import call_command
from django.test import Client
from django.test import override_settings
from reports.test_business_command_center import BusinessCommandCenterApiTests, FEATURES
from fixtures import parts_summary, parts_details

for name, value in FEATURES.items():
    setattr(settings, name, value)
settings.ENABLE_AVAILABILITY_COMMAND_CENTER_HOME = 'Production'
settings.ENABLE_PREMIUM_REPORTING_HUB = 'Production'
settings.ENABLE_CODEX_CHATBOT = 'Production'
settings.ENABLE_CODEX_ADMIN = 'Production'
settings.SECURE_SSL_REDIRECT = False
settings.ALLOWED_HOSTS = ['127.0.0.1', 'localhost', 'testserver']
logging.getLogger('django.request').setLevel(logging.CRITICAL)
RENDER_LOCK = RLock()


def blocked_source(*args, **kwargs):
    raise RuntimeError('External source unavailable in isolated UI tests')


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path.startswith('/static/'):
            relative = self.path.split('?', 1)[0][8:]
            target = finders.find(relative) if '..' not in Path(relative).parts else None
            if not target:
                self.send_error(404)
                return
            data = Path(target).read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', mimetypes.guess_type(target)[0] or 'application/octet-stream')
        else:
            variant = self.headers.get('X-Presentation-Test', 'responsive')
            with RENDER_LOCK, override_settings(MINING360_RESPONSIVE_UI_ENABLED=variant != 'legacy',
                                   MINING360_BUSINESS_THEME_ENABLED=variant == 'responsive'):
                active_client = Client(raise_request_exception=False) if self.path.split('?')[0]=='/login/' else self.server.client
                response = active_client.get(self.path, HTTP_HOST='127.0.0.1')
            data = b''.join(response.streaming_content) if response.streaming else response.content
            self.send_response(response.status_code)
            for name in ('Content-Type', 'Location', 'Content-Disposition'):
                if name in response:
                    self.send_header(name, response[name])
            if 'text/html' in response.get('Content-Type', ''):
                marker = b'<span style="position:fixed;bottom:0;right:0;z-index:9999;background:#fff;color:#333;font:9px monospace;pointer-events:none">LOCAL UI TEST FIXTURES</span>'
                data = data.replace(b'</body>', marker + b'</body>')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError,ConnectionError,OSError):
            pass # The test browser may close a PDF/assets request on navigation.

    def do_POST(self):
        # No preview test may publish, deploy, sync, send messages or save config.
        self.send_error(405, 'Mutations disabled in isolated UI fixture host')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    if not (OUT / 'fixtures.sqlite3').exists():
        call_command('migrate', verbosity=0, interactive=False)
        fixture = BusinessCommandCenterApiTests('test_page_and_bootstrap_load_without_published_mapping')
        fixture.setUp()
    client = Client(raise_request_exception=False)
    admin=User.objects.get(username='command-admin')
    client.force_login(admin)
    from reports.test_homepage_availability_command_center import HomepageAvailabilityCommandCenterTests, SAMPLE_ROWS, SAMPLE_FUEL_ROWS
    from reports.homepage_availability_service import HomepageAvailabilityService
    home_fixture=HomepageAvailabilityCommandCenterTests('test_default_request_is_ytd_overall')
    with patch.object(User.objects,'create_superuser',return_value=admin):
        home_fixture.setUp()
    from reports.models import PowerBIReport as ReportConfig
    from reports.models import AIAgentRoutingConfiguration
    AIAgentRoutingConfiguration.objects.get_or_create(name='UI fixture',defaults={'routing_enabled':False})
    from reports.powerbi import PowerBIReport as CatalogReport
    from django.utils import timezone
    # Approved visual universes, with test IDs and no credentials/embed tokens.
    catalog=[]
    from reports.live_sources import LiveSource
    fixture_source=LiveSource(key='ui-test',name='LOCAL UI TEST SOURCE',engine='SQL Server',
        server='unavailable-test-source',database='UIFixture',user='',password='',port=1433,
        owner='Test only',status='Unavailable',status_class='neutral',
        description='Presentation test only; all external connections are blocked.',views=())
    for index,name in enumerate(('Fleet Performance Report','Mine Logistics Report','Prime Movers Operational Status')):
        report_id=f'00000000-0000-4000-8000-{index+1:012d}'
        ReportConfig.objects.update_or_create(report_id=report_id,defaults={
            'report_name':name,'display_name':name,'workspace_id':'ui-test-workspace',
            'semantic_model_id':'ui-test-model','is_active':True,'section':home_fixture.section})
        catalog.append(CatalogReport(report_id,name,name,'ui-test-model','','','PowerBIReport','2026-10-31','Completed'))
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.client = client
    print(json.dumps({'ready': True, 'port': args.port, 'data': 'isolated test fixtures'}), flush=True)
    with ExitStack() as stack:
        stack.enter_context(patch('requests.sessions.Session.send', side_effect=blocked_source))
        stack.enter_context(patch('pyodbc.connect', side_effect=blocked_source))
        stack.enter_context(patch('socket.socket.connect', side_effect=blocked_source))
        stack.enter_context(patch('reports.views.list_workspace_reports_with_refresh',return_value=catalog))
        stack.enter_context(patch('reports.views.list_live_sources',return_value=[fixture_source]))
        stack.enter_context(patch('reports.views.get_live_source',return_value=fixture_source))
        stack.enter_context(patch('reports.reporting_configuration_views.list_workspace_reports',return_value=catalog))
        stack.enter_context(patch('reports.reporting_configuration_views.list_workspace_reports_with_refresh',return_value=catalog))
        stack.enter_context(patch('reports.homepage_availability_service.execute_dax_via_flow',return_value={'firstTableRows':SAMPLE_ROWS}))
        stack.enter_context(patch('reports.homepage_fuel_service.execute_dax_via_flow',return_value={'firstTableRows':SAMPLE_FUEL_ROWS}))
        stack.enter_context(patch.object(HomepageAvailabilityService,'_refresh_metadata',return_value=('2026-10-31','Completed')))
        stack.enter_context(patch('reports.parts_fulfillment_service.PartsFulfillmentService.summary',side_effect=parts_summary))
        stack.enter_context(patch('reports.parts_fulfillment_service.PartsFulfillmentService.details',side_effect=parts_details))
        server.serve_forever()
