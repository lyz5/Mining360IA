from __future__ import annotations

import base64
import hashlib
import io
import socket
import time

from django.utils import timezone

from deployment.models import DeploymentAuditLog, DeploymentTarget
from deployment.services.credentials import credential_secret
from deployment.services.security import DeploymentNetworkSecurityService


def _fingerprint(key) -> str:
    digest = hashlib.sha256(key.asbytes()).digest()
    return "SHA256:" + base64.b64encode(digest).decode().rstrip("=")


def _load_private_key(paramiko, value: str):
    errors = []
    for key_class in (paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey):
        try:
            return key_class.from_private_key(io.StringIO(value))
        except Exception as exc:
            errors.append(str(exc))
    raise ValueError("The configured SSH private key could not be loaded.")


class DeploymentConnectionService:
    def test(self, target: DeploymentTarget, *, user=None) -> dict:
        started = time.monotonic()
        host = target.connection_host
        addresses = DeploymentNetworkSecurityService().resolve_and_validate(host)
        result = {
            "reachable": False,
            "dns_resolved": True,
            "resolved_addresses": addresses,
            "tcp_connected": False,
            "ssh_connected": False,
            "host_key_verified": False,
            "status": "failed",
        }
        try:
            with socket.create_connection((addresses[0], target.port), timeout=5):
                result["reachable"] = True
                result["tcp_connected"] = True
        except OSError as exc:
            result["message"] = f"TCP connection to port {target.port} failed: {exc}"
            return self._save(target, result, user, started)

        if target.connection_mode != "ssh":
            result.update(status="warning", message="Deployment Agent mode is not implemented in Phase 1.")
            return self._save(target, result, user, started)
        try:
            import paramiko
        except ImportError:
            result.update(status="warning", message="Paramiko is not installed; only the network check was completed.")
            return self._save(target, result, user, started)

        transport = None
        try:
            sock = socket.create_connection((addresses[0], target.port), timeout=8)
            transport = paramiko.Transport(sock)
            transport.banner_timeout = 8
            transport.start_client(timeout=8)
            fingerprint = _fingerprint(transport.get_remote_server_key())
            result["host_key_fingerprint"] = fingerprint
            if target.host_key_fingerprint and target.host_key_fingerprint != fingerprint:
                result.update(status="blocked", message="The SSH host key changed. Connection blocked.")
                return self._save(target, result, user, started)
            if not target.host_key_verified:
                result.update(status="host_key_pending", message="Validate the SSH host key before authentication.")
                return self._save(target, result, user, started)
            result["host_key_verified"] = True
            secret = credential_secret(target.credential)
            if not secret or not target.ssh_username:
                result.update(status="not_configured", message="SSH username or credential is not configured.")
                return self._save(target, result, user, started)
            if target.credential.credential_type == "ssh_private_key":
                transport.auth_publickey(target.ssh_username, _load_private_key(paramiko, secret))
            elif target.credential.credential_type == "ssh_password":
                transport.auth_password(target.ssh_username, secret)
            else:
                raise ValueError("The selected credential cannot be used for SSH.")
            result.update(
                ssh_connected=transport.is_authenticated(),
                host_key_verified=True,
                remote_user=target.ssh_username,
                status="success" if transport.is_authenticated() else "failed",
                message="Connection successful." if transport.is_authenticated() else "SSH authentication failed.",
            )
        except Exception as exc:
            result.update(status="failed", message=f"SSH connection failed: {exc}")
        finally:
            if transport:
                transport.close()
        return self._save(target, result, user, started)

    def _save(self, target, result, user, started):
        result["latency_ms"] = int((time.monotonic() - started) * 1000)
        target.last_connection_test_at = timezone.now()
        target.last_connection_result = result
        if result["status"] == "success":
            target.status = "Online"
            target.last_successful_connection_at = timezone.now()
        elif result["status"] == "blocked":
            target.status = "Blocked"
        elif result.get("tcp_connected"):
            target.status = "Not Configured"
        else:
            target.status = "Offline"
        target.save(update_fields=["last_connection_test_at", "last_connection_result", "last_successful_connection_at", "status", "updated_at"])
        DeploymentAuditLog.objects.create(user=user, target=target, action="TEST_CONNECTION", details_json={"result": result})
        return result
