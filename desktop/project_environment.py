"""Development environment shared by the desktop and its services."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def project_python(root=ROOT):
    for base in (root, root.parent):
        candidate = base / '.venv' / 'Scripts' / 'python.exe'
        if candidate.is_file() and (base / '.venv' / 'pyvenv.cfg').is_file():
            return candidate.resolve()
    raise RuntimeError('Project .venv missing; global Python is not supported.')


def configure(root=ROOT, host='mining360-dev.neemba.local'):
    if os.environ.get('MINING360_CONTROL_ENVIRONMENT', 'Development') != 'Development':
        raise RuntimeError('This launcher is restricted to Development.')
    os.environ.update({
        'DJANGO_SETTINGS_MODULE': 'Mining360IA.settings',
        'MINING360_CONTROL_ENVIRONMENT': 'Development',
        'MINING360_DEBUG': '1',
        'MINING360_DATABASE_ENGINE': 'sqlite',
        'MINING360_SQLITE_PATH': str(root / 'db.sqlite3'),
        'MINING360_SQL_CONFIG_STORE': '0',
        'BUSINESS_REVENUE_AUTO_SYNC': 'true',
        'MINING360_ALLOWED_HOSTS': f'127.0.0.1,localhost,{host}',
        'MINING360_CSRF_TRUSTED_ORIGINS': f'http://{host},https://{host}',
        'MINING360_USE_X_FORWARDED_HOST': '1',
        'MINING360_PUBLIC_BASE_URL': f'https://{host}',
        'ENTRA_REDIRECT_URI': f'https://{host}/auth/callback/',
        'AZURE_AD_REDIRECT_URI': f'https://{host}/auth/callback/',
        'ENABLE_CODEX_CHATBOT': 'Admin Only',
        'ENABLE_CODEX_ADMIN': 'Admin Only',
        'CODEX_CHATBOT_APP_SERVER_ENABLED': '1',
        'CODEX_CHATBOT_WEB_SEARCH_ENABLED': '1',
        'PYTHONUNBUFFERED': '1',
        'PYTHONIOENCODING': 'utf-8',
        'PYTHONUTF8': '1',
    })
