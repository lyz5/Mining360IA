"""Opt-in, loopback-only BODEFM snapshot preview. Never use on the server."""
import json
import os
import socket
from pathlib import Path

if os.getenv('MINING360_LOCAL_PREVIEW') != '1' or socket.gethostname().upper() == 'BODEFM':
    raise RuntimeError('This profile is restricted to the isolated workstation preview.')

LOCAL_PREVIEW_STATE = Path(os.environ['MINING360_LOCAL_PREVIEW_STATE']).resolve()
_local = json.loads((LOCAL_PREVIEW_STATE / 'instance.private.json').read_text(encoding='utf-8'))
if _local['database'] != 'Mining360App_BODEFM_Local_20261116':
    raise RuntimeError('Unexpected local preview database.')

# Set before loading the base profile, so ambient production configuration cannot win.
os.environ.update({
    'MINING360_DEBUG': '1', 'MINING360_DATABASE_ENGINE': 'mssql',
    'MINING360_APP_SQL_SERVER': r'localhost\MSSQL_IA',
    'MINING360_APP_SQL_DATABASE': _local['database'], 'MINING360_APP_SQL_PORT': '',
    'MINING360_APP_SQL_USER': '', 'MINING360_APP_SQL_PASSWORD': '',
    'MINING360_APP_SQL_DRIVER': 'ODBC Driver 18 for SQL Server',
    'MINING360_APP_SQL_EXTRA_PARAMS': 'Encrypt=optional;TrustServerCertificate=yes;Connection Timeout=10',
    'MINING360_SECRET_KEY': _local['secret_key'],
    'MINING360_CONFIG_ENCRYPTION_KEY': _local['encryption_key'],
    'MINING360_SQL_CONFIG_STORE': '0',
    'BUSINESS_REVENUE_AUTO_SYNC': 'false', 'PARTS_FULFILLMENT_AUTO_SYNC': 'false', 'PARTS_SALES_AUTO_SYNC': 'false',
    'BUSINESS_MAPPING_AUTO_SYNC_ON_STUDIO_OPEN': 'false',
    'MINING360_DASHBOARD_CONFIG': str(LOCAL_PREVIEW_STATE / 'dashboard-disabled.json'),
    'MINING360_EMAIL_CODE_LOGIN_ENABLED': '1',
    'MINING360_ALLOWED_HOSTS': '127.0.0.1,localhost',
    'MINING360_PUBLIC_BASE_URL': 'http://localhost:8016',
    'MINING360_SECURE_SSL_REDIRECT': '0',
    'MINING360_SESSION_COOKIE_SECURE': '0', 'MINING360_CSRF_COOKIE_SECURE': '0',
    'MINING360_USE_X_FORWARDED_HOST': '0',
})

from .settings import *  # noqa: E402,F401,F403

ALLOWED_HOSTS = ['localhost', '127.0.0.1']
CSRF_TRUSTED_ORIGINS = ['http://localhost:8016', 'http://127.0.0.1:8016']
SESSION_COOKIE_NAME = 'm360_local_preview_session'
CSRF_COOKIE_NAME = 'm360_local_preview_csrf'
SESSION_COOKIE_DOMAIN = CSRF_COOKIE_DOMAIN = None
USE_X_FORWARDED_HOST = False
SECURE_PROXY_SSL_HEADER = None
CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'bodefm-local-preview'}}
MIDDLEWARE = [*MIDDLEWARE, 'deployment.local_preview.LocalPreviewBanner']
LOCAL_PREVIEW_REAL_EMAIL = _local.get('real_email_enabled') is True
EMAIL_BACKEND = ('django.core.mail.backends.smtp.EmailBackend' if LOCAL_PREVIEW_REAL_EMAIL
                 else 'django.core.mail.backends.filebased.EmailBackend')
EMAIL_FILE_PATH = str(LOCAL_PREVIEW_STATE / 'mailbox')
MEDIA_ROOT = LOCAL_PREVIEW_STATE / 'media'
PARTS_FULFILLMENT_AUTO_SYNC_DIRECTORY = LOCAL_PREVIEW_STATE / 'parts-refresh'
STATIC_ROOT = LOCAL_PREVIEW_STATE / 'static'
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}
LOGGING = {'version': 1, 'disable_existing_loggers': False,
           'handlers': {'console': {'class': 'logging.StreamHandler'}},
           'root': {'handlers': ['console'], 'level': 'WARNING'}}
