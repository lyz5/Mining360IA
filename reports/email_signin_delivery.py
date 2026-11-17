"""Deliver only a fixed sign-in message, through a configured corporate sender."""
from urllib.parse import urlsplit

import requests
from django.conf import settings
from django.core.mail import get_connection, send_mail
from django.core.validators import validate_email
from django.views.decorators.debug import sensitive_variables

from .models import SystemIntegrationConfig
from .system_configuration_service import decrypt_secrets

HTTP = requests.Session()
HTTP.trust_env = False


def validate_flow_url(value):
    try:
        url = urlsplit(value)
        port = url.port
    except ValueError:
        raise ValueError('Use the HTTPS URL of a dedicated corporate email flow.') from None
    if (url.scheme != 'https' or not url.hostname or port not in (None, 443)
            or url.username or url.password or url.fragment
            or not url.hostname.endswith(('.api.powerplatform.com', '.logic.azure.com'))):
        raise ValueError('Use the HTTPS URL of a dedicated corporate email flow.')


def configuration_ready():
    try:
        item = SystemIntegrationConfig.objects.filter(integration_type='Notification', code='email-signin', is_active=True).first()
        if not item:
            return False
        config, secret = item.settings_json or {}, decrypt_secrets(item)
        validate_email(config.get('sender_email', ''))
        if config.get('transport') == 'Power Automate':
            validate_flow_url(secret.get('flow_url', ''))
            return True
        return bool(config.get('transport') == 'SMTP' and config.get('smtp_host')
                    and bool(config.get('smtp_tls')) != bool(config.get('smtp_ssl'))
                    and (not config.get('smtp_username') or secret.get('smtp_password'))
                    and 1 <= int(config.get('smtp_port') or 587) <= 65535)
    except Exception:
        return False


@sensitive_variables('address', 'code', 'body', 'flow', 'secret')
def send_code(address, code, minutes):
    subject = 'Your Mining360 sign-in code'
    body = (f'Your Mining360 sign-in code is: {code}\n\n'
            f'This code expires in {minutes} minutes and can be used once.\n'
            'Do not share it. Mining360 will never ask for your Windows password by email.\n\n'
            'If you did not request this code, ignore this message.\nMining360 | Neemba')
    item = SystemIntegrationConfig.objects.filter(integration_type='Notification', code='email-signin', is_active=True).first()
    if not item:
        raise RuntimeError('Corporate email delivery must be configured.')
    config = dict(item.settings_json or {})
    secret = decrypt_secrets(item)
    sender = str(config.get('sender_email') or '').strip()
    validate_email(sender)
    if config.get('transport') == 'Power Automate':
        flow = secret.get('flow_url', '')
        validate_flow_url(flow)
        # Dedicated flow contract, not an invocation of the existing DAX flow.
        response = HTTP.post(flow, json={'recipient': address, 'subject': subject, 'body': body}, timeout=(4, 15), allow_redirects=False)
        if response.status_code not in (200, 204):
            raise RuntimeError('Email delivery unavailable.')
        return
    if config.get('transport') != 'SMTP' or not str(config.get('smtp_host') or '').strip():
        raise RuntimeError('Corporate email delivery must be configured.')
    use_tls, use_ssl = bool(config.get('smtp_tls')), bool(config.get('smtp_ssl'))
    if not (use_tls or use_ssl) or use_tls and use_ssl:
        raise RuntimeError('SMTP must use TLS or SSL.')
    with get_connection(
        host=config['smtp_host'], port=int(config.get('smtp_port') or 587),
        username=config.get('smtp_username') or '', password=secret.get('smtp_password') or '',
        use_tls=use_tls, use_ssl=use_ssl, timeout=10,
    ) as connection:
        sent = send_mail(subject, body, sender, [address], fail_silently=False, connection=connection)
    if sent != 1:
        raise RuntimeError('Email delivery unavailable.')
