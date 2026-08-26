from __future__ import annotations

import socket
import time

from deployment.os_adapters import adapter_for
from deployment.models import DeploymentAuditLog
from deployment.services.connection import _fingerprint, _load_private_key
from deployment.services.credentials import credential_secret
from deployment.services.security import DeploymentNetworkSecurityService, sanitize_log_message


class DeploymentRemoteReadService:
    """Executes only predefined, read-only checks from an OS adapter."""

    def run_checks(self, target, *, check_codes=None, timeout=20):
        commands = adapter_for(target.os_family).precheck_commands()
        selected = list(check_codes or commands.keys())
        unknown = sorted(set(selected) - set(commands))
        if unknown:
            raise ValueError(f"Unsupported pre-check codes: {', '.join(unknown)}")
        return {
            code: self._run_one(target, code, commands[code], timeout)
            for code in selected
        }

    def _run_one(self, target, code, command, timeout):
        started = time.monotonic()
        transport = None
        try:
            transport = self._connect(target, timeout=timeout)
            return self._execute(transport, code, command, timeout)
        except Exception as exc:
            return {
                "code": code,
                "success": False,
                "exit_code": None,
                "stdout": "",
                "stderr": sanitize_log_message(str(exc))[:2000],
                "duration_ms": int((time.monotonic() - started) * 1000),
            }
        finally:
            if transport:
                transport.close()

    def _connect(self, target, *, timeout):
        try:
            import paramiko
        except ImportError as exc:
            raise RuntimeError("Paramiko is required for remote pre-checks.") from exc
        addresses = DeploymentNetworkSecurityService().resolve_and_validate(target.connection_host)
        sock = socket.create_connection((addresses[0], target.port), timeout=timeout)
        transport = paramiko.Transport(sock)
        transport.banner_timeout = timeout
        try:
            transport.start_client(timeout=timeout)
            fingerprint = _fingerprint(transport.get_remote_server_key())
            if not target.host_key_verified or fingerprint != target.host_key_fingerprint:
                raise RuntimeError("The SSH host key is not trusted or changed.")
            secret = credential_secret(target.credential)
            if not secret or not target.ssh_username:
                raise RuntimeError("SSH credential is not configured.")
            if target.credential.credential_type == "ssh_private_key":
                transport.auth_publickey(target.ssh_username, _load_private_key(paramiko, secret))
            elif target.credential.credential_type == "ssh_password":
                transport.auth_password(target.ssh_username, secret)
            else:
                raise RuntimeError("The configured credential is not valid for SSH.")
            if not transport.is_authenticated():
                raise RuntimeError("SSH authentication failed.")
            return transport
        except Exception:
            transport.close()
            raise

    def _execute(self, transport, code, command, timeout):
        started = time.monotonic()
        channel = transport.open_session(timeout=timeout)
        channel.settimeout(timeout)
        try:
            channel.exec_command(command)
            stdout = channel.makefile("r", -1).read()
            stderr = channel.makefile_stderr("r", -1).read()
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")
            exit_code = channel.recv_exit_status()
            return {
                "code": code,
                "success": exit_code == 0,
                "exit_code": exit_code,
                "stdout": sanitize_log_message(stdout.strip())[:4000],
                "stderr": sanitize_log_message(stderr.strip())[:2000],
                "duration_ms": int((time.monotonic() - started) * 1000),
            }
        except socket.timeout:
            return {
                "code": code,
                "success": False,
                "exit_code": None,
                "stdout": "",
                "stderr": "Remote check timed out.",
                "duration_ms": int((time.monotonic() - started) * 1000),
            }
        finally:
            channel.close()


class DeploymentRemoteRemediationService(DeploymentRemoteReadService):
    """Runs only explicitly allowlisted, reversible target remediations."""

    def run(self, target, action_code, *, user=None, timeout=30):
        commands = getattr(adapter_for(target.os_family), "remediation_commands", lambda: {})()
        if action_code not in commands:
            raise ValueError(f"Unsupported safe remediation: {action_code}")
        result = self._run_one(target, action_code, commands[action_code], timeout)
        DeploymentAuditLog.objects.create(
            user=user,
            target=target,
            action="SYSTEM_DOCTOR_REMEDIATION",
            details_json={
                "action_code": action_code,
                "success": result["success"],
                "exit_code": result["exit_code"],
            },
        )
        return result
