"""Permit only the dedicated email flow from an otherwise offline preview."""
import ipaddress
import socket
import threading
from urllib.parse import urlsplit

import requests
from django.views.decorators.debug import sensitive_variables


class EmailEgressPolicy:
    def __init__(self):
        self._mail_url = None
        self._connection = threading.local()

    @sensitive_variables('url')
    def allow_email_flow(self, url):
        from reports.email_signin_delivery import validate_flow_url
        validate_flow_url(url)
        self._mail_url = requests.Request('POST', url).prepare().url

    def socket_allowed(self, address):
        if not isinstance(address, tuple) or len(address) < 2 or address[1] != 443:
            return False
        return str(address[0]).split('%')[0] in getattr(self._connection, 'addresses', ())

    @sensitive_variables('request')
    def send(self, original_send, session, request, **kwargs):
        url = urlsplit(request.url)
        try:
            loopback = url.hostname == 'localhost' or ipaddress.ip_address(url.hostname).is_loopback
        except ValueError:
            loopback = False
        if loopback:
            return original_send(session, request, **kwargs)
        if (not self._mail_url or request.url != self._mail_url or request.method != 'POST'
                or kwargs.get('allow_redirects', True) or kwargs.get('verify') is False):
            raise OSError('Only the configured email flow is permitted outside the local preview.')
        addresses = {str(row[4][0]).split('%')[0] for row in socket.getaddrinfo(url.hostname, 443, type=socket.SOCK_STREAM)}
        previous = getattr(self._connection, 'addresses', ())
        self._connection.addresses = addresses
        try:
            return original_send(session, request, **kwargs)
        finally:
            self._connection.addresses = previous
