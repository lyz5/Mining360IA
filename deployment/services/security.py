from __future__ import annotations

import ipaddress
import os
import re
import socket


DEFAULT_ALLOWED_NETWORKS = "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fc00::/7"
SECRET_PATTERNS = (
    re.compile(r"(?i)(password|secret|token|api[_-]?key)\s*[=:]\s*([^\s,;]+)"),
    re.compile(r"(?i)(authorization:\s*bearer)\s+[^\s]+"),
)


class DeploymentNetworkSecurityService:
    def __init__(self, allowed_networks=None):
        raw = allowed_networks or os.getenv("MINING360_DEPLOYMENT_ALLOWED_NETWORKS", DEFAULT_ALLOWED_NETWORKS)
        self.allowed_networks = [ipaddress.ip_network(value.strip(), strict=False) for value in raw.split(",") if value.strip()]

    def resolve_and_validate(self, host: str) -> list[str]:
        clean = str(host or "").strip().rstrip(".")
        if not clean or "/" in clean or "://" in clean:
            raise ValueError("A valid hostname or IP address is required.")
        try:
            addresses = {str(ipaddress.ip_address(clean))}
        except ValueError:
            try:
                addresses = {item[4][0] for item in socket.getaddrinfo(clean, None, type=socket.SOCK_STREAM)}
            except socket.gaierror as exc:
                raise ValueError(f"DNS resolution failed for {clean}.") from exc
        if not addresses:
            raise ValueError("The target did not resolve to an IP address.")
        for value in addresses:
            address = ipaddress.ip_address(value)
            if address.is_loopback or address.is_link_local or address.is_multicast or address.is_unspecified:
                raise ValueError(f"Address {address} is not permitted for deployment.")
            if not any(address in network for network in self.allowed_networks):
                raise ValueError(f"Address {address} is outside the allowed deployment networks.")
        return sorted(addresses)


def sanitize_log_message(message: str) -> str:
    value = str(message or "")
    for pattern in SECRET_PATTERNS:
        value = pattern.sub(lambda match: f"{match.group(1)}=********", value)
    return value[:10000]
