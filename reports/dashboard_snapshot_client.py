"""Read BODEFM snapshots over the existing authenticated, pinned SSH connection."""
import hashlib
import json
import socket
from datetime import datetime, timedelta

from django.utils import timezone

from .dashboard_snapshots import access_contract, configuration, directory, _read, _write


def remote_snapshot(kind, user, params):
    import paramiko
    from deployment.models import DeploymentTarget
    from deployment.services.connection import _fingerprint
    from .homepage_availability_service import HomepageAvailabilityError
    from .business_command_center_service import BusinessCommandCenterInputError
    error_class = HomepageAvailabilityError if kind == 'excellence' else BusinessCommandCenterInputError
    contract = access_contract(user)
    params = {key: params.get(key) for key in params if params.get(key) not in ('', None)}
    request = {'kind': kind, 'identity': contract['identity'], 'contract': contract, 'params': params}
    key = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
    path = directory() / ('remote-' + key + '.json')
    previous = _read(path)
    if previous and timezone.now() - datetime.fromisoformat(previous['received_at']) < timedelta(minutes=5):
        return previous['payload']
    config = configuration()
    target = DeploymentTarget.objects.get(pk=config['deployment_target_id'])
    transport = None
    try:
        if target.connection_host.casefold() != 'bodefm' or not target.host_key_verified:
            raise RuntimeError('Unapproved snapshot server')
        transport = paramiko.Transport(socket.create_connection((config['address'], target.port), timeout=10))
        transport.banner_timeout = 15
        transport.auth_timeout = 15
        transport.start_client(timeout=15)
        if _fingerprint(transport.get_remote_server_key()) != target.host_key_fingerprint:
            raise RuntimeError('Snapshot server identity changed')
        key = paramiko.Ed25519Key.from_private_key_file(config['identity_file'])
        transport.auth_publickey(target.ssh_username, key)
        channel = transport.open_session(timeout=15)
        channel.settimeout(240)
        # Fixed executable and entry point: request values go only to stdin.
        channel.exec_command('C:\\Mining360\\venv\\Scripts\\python.exe C:\\Mining360\\app\\deployment\\windows\\dashboard_snapshot_runner.py --request')
        channel.sendall(json.dumps(request).encode('utf-8'))
        channel.shutdown_write()
        raw = channel.makefile('rb').read(20 * 1024 * 1024)
        status = channel.recv_exit_status()
        result = json.loads(raw.decode('utf-8'))
        if status or not result.get('ok'):
            # Authorization failures must never fall back to an old snapshot.
            if result.get('code') == 'access_denied':
                raise PermissionError('Snapshot access denied')
            raise RuntimeError('Snapshot unavailable')
        if result.get('contract') != contract:
            raise PermissionError('Snapshot scope mismatch')
        payload = result['payload']
        payload.setdefault('dashboard_snapshot', {}).update({'origin': 'BODEFM', 'offline': False})
        _write(path, {'received_at': timezone.now().isoformat(), 'payload': payload})
        return payload
    except PermissionError:
        # A known central revocation must also prevent a later offline fallback.
        path.unlink(missing_ok=True)
        raise error_class('The BODEFM snapshot is not authorized for your current access scope.') from None
    except Exception:
        if previous:
            payload = previous['payload']
            payload.setdefault('dashboard_snapshot', {}).update({'origin': 'BODEFM', 'offline': True, 'stale': True})
            return payload
        raise error_class('The BODEFM snapshot is not available yet. Please retry shortly.') from None
    finally:
        if transport:
            transport.close()
