"""Run an isolated local snapshot, with no workers or external connections.

This is a workstation launcher, not part of the production WSGI entry point.
"""
import argparse
import html
import ipaddress
import json
import os
import re
import socket
import sys
from pathlib import Path


def install_network_guards(database):
    """Block external Python sockets and native ODBC targets in this process."""
    from deployment.local_mail_policy import EmailEgressPolicy
    import requests
    policy = EmailEgressPolicy()
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def local_address(address):
        if not isinstance(address, tuple):
            return False
        host = str(address[0]).split('%')[0].lower()
        if host == 'localhost':
            return True
        try:
            if ipaddress.ip_address(host).is_loopback:
                return True
        except ValueError:
            pass
        return policy.socket_allowed(address)

    def guarded_connect(sock, address):
        if not local_address(address):
            raise OSError('External connections are disabled in the local snapshot.')
        return original_connect(sock, address)

    def guarded_connect_ex(sock, address):
        if not local_address(address):
            raise OSError('External connections are disabled in the local snapshot.')
        return original_connect_ex(sock, address)

    socket.socket.connect = guarded_connect
    socket.socket.connect_ex = guarded_connect_ex
    import pyodbc
    original_odbc = pyodbc.connect

    def guarded_odbc(connection_string, *args, **kwargs):
        fields = dict((key.strip().lower(), value.strip('{} '))
                      for key, value in re.findall(r'([^;=]+)=([^;]*)', connection_string))
        if (fields.get('server', '').lower() != r'localhost\mssql_ia'
                or fields.get('database', '').lower() != database.lower()):
            raise RuntimeError('ODBC is restricted to this preview database.')
        return original_odbc(connection_string, *args, **kwargs)

    pyodbc.connect = guarded_odbc
    original_send = requests.sessions.Session.send

    def guarded_send(session, request, **kwargs):
        return policy.send(original_send, session, request, **kwargs)

    requests.sessions.Session.send = guarded_send
    return policy


class LocalPreviewApplication:
    def __init__(self, application, state):
        self.application, self.state = application, state

    def __call__(self, environ, start_response):
        host = environ.get('HTTP_HOST', '').split(':')[0]
        if host not in ('localhost', '127.0.0.1') or environ.get('REMOTE_ADDR') not in ('127.0.0.1', '::1'):
            start_response('403 Forbidden', [('Content-Type', 'text/plain')])
            return [b'Local preview only.']
        if environ.get('PATH_INFO') == '/__local__/mailbox/':
            from django.conf import settings
            if getattr(settings, 'LOCAL_PREVIEW_REAL_EMAIL', False):
                start_response('200 OK', [('Content-Type', 'text/plain; charset=utf-8'), ('Cache-Control', 'private, no-store')])
                return [b'Real email delivery is enabled. Codes are sent to your authorized email address; no local code is stored.']
            messages = sorted((self.state / 'mailbox').glob('*.log'), key=lambda f: f.stat().st_mtime, reverse=True)[:20]
            body = ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
                    '<title>Mining360 | Local test mailbox</title>'
                    '<style>body{font:16px system-ui;margin:2rem;background:#f4f7fb;color:#062a4d}pre{white-space:pre-wrap;background:white;padding:1rem;border:1px solid #ddd}a{color:#005b9f}</style>'
                    '<h1>Local test mailbox</h1><p>LOCAL SNAPSHOT · No real email is sent. Codes expire after 10 minutes.</p>'
                    '<p><a href="/email-sign-in/">Sign in</a> · <a href="/">Application</a> · <a href="/__local__/mailbox/">Refresh</a></p>')
            body += ''.join('<pre>' + html.escape(message.read_text(encoding='utf-8', errors='replace')) + '</pre>' for message in messages)
            if not messages:
                body += '<p>No messages yet. Request a code using an active email already listed in the copied Config → Users.</p>'
            start_response('200 OK', [('Content-Type', 'text/html; charset=utf-8'), ('Cache-Control', 'private, no-store'), ('X-Frame-Options', 'DENY')])
            return [(body + '</html>').encode('utf-8')]

        def with_local_header(status, headers, exc_info=None):
            from django.conf import settings
            delivery = 'email delivery enabled' if getattr(settings, 'LOCAL_PREVIEW_REAL_EMAIL', False) else 'outbound disabled'
            headers.append(('X-Mining360-Environment', 'Local BODEFM snapshot 2026-11-15; ' + delivery))
            return start_response(status, headers, exc_info)
        return self.application(environ, with_local_header)


class LocalPreviewBanner:
    """Visible environment/date marker, installed only by the preview profile."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if (not response.streaming and response.get('Content-Type', '').startswith('text/html')
                and b'<body' in response.content):
            from django.conf import settings
            email_note = (b'Real email delivery' if getattr(settings, 'LOCAL_PREVIEW_REAL_EMAIL', False)
                          else b'No real emails &middot; <a href="/__local__/mailbox/" target="_blank" rel="noopener">Local mailbox</a>')
            banner = (b'<aside aria-label="Local test environment" style="position:fixed;bottom:8px;left:8px;'
                      b'z-index:2147483647;box-sizing:border-box;max-width:calc(100vw - 32px);background:#fff2aa;color:#062a4d;'
                      b'padding:8px 12px;border:1px solid #d4a800;border-radius:8px;font:12px system-ui">'
                      b'LOCAL TEST &middot; BODEFM snapshot 15 Nov 2026 &middot; ' + email_note + b'</aside>')
            response.content = re.sub(rb'(<body\b[^>]*>)', lambda match: match[0] + banner, response.content, count=1)
            response['Content-Length'] = str(len(response.content))
        return response


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-directory', required=True, type=Path)
    args = parser.parse_args()
    if socket.gethostname().upper() == 'BODEFM':
        raise SystemExit('Refusing to start a local preview on BODEFM.')
    state = args.state_directory.resolve()
    config = json.loads((state / 'instance.private.json').read_text(encoding='utf-8'))
    if config['database'] != 'Mining360App_BODEFM_Local_20261116' or not (state / 'ready.json').exists():
        raise SystemExit('The isolated local database must be prepared and verified first.')
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    os.chdir(root)
    os.environ.update(MINING360_LOCAL_PREVIEW='1', MINING360_LOCAL_PREVIEW_STATE=str(state),
                      DJANGO_SETTINGS_MODULE='Mining360IA.settings_local_preview')
    policy = install_network_guards(config['database'])
    from django.core.wsgi import get_wsgi_application
    from django.contrib.staticfiles.handlers import StaticFilesHandler
    from waitress import serve
    django_app = get_wsgi_application()
    from django.conf import settings
    if settings.LOCAL_PREVIEW_REAL_EMAIL:
        from reports.models import SystemIntegrationConfig
        from reports.system_configuration_service import decrypt_secrets
        item = SystemIntegrationConfig.objects.filter(code='email-signin', integration_type='Notification', is_active=True).first()
        if not item or (item.settings_json or {}).get('transport') != 'Power Automate':
            raise SystemExit('Configure the dedicated email flow before enabling real delivery.')
        policy.allow_email_flow(decrypt_secrets(item).get('flow_url', ''))
    application = LocalPreviewApplication(StaticFilesHandler(django_app), state)
    print('Mining360 local preview: http://localhost:8016/ | Real email: '+str(settings.LOCAL_PREVIEW_REAL_EMAIL), flush=True)
    serve(application, host='127.0.0.1', port=8016, threads=4, expose_tracebacks=False)


if __name__ == '__main__':
    main()
