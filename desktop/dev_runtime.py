"""Start local Development without changing DNS, certificates or trust stores."""
import argparse
import ctypes
import json
import os
import socket
import subprocess
import time
from dataclasses import asdict

from desktop.project_environment import ROOT, configure, project_python


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='mining360-dev.neemba.local')
    parser.add_argument('--https-port', type=int, default=443)
    parser.add_argument('--upstream-port', type=int, default=8001)
    args = parser.parse_args()
    configure(host=args.host)
    # Serialize independent shortcut/controller invocations on this machine.
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    mutex = kernel.CreateMutexW(None, False, 'Local\\Mining360DevelopmentStartup')
    if not mutex:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == 183:
        kernel.CloseHandle(mutex)
        raise SystemExit('Development startup already in progress.')
    try:
        start(args)
    finally:
        kernel.CloseHandle(mutex)


def start(args):
    from desktop.control_core import Mining360Controller
    controller = Mining360Controller()
    if controller._listener_pids({args.upstream_port}):
        raise SystemExit('Application port already occupied; no second instance started.')
    if controller.managed_processes():
        raise SystemExit('Existing runtime components detected; use the verified restart action.')
    certificate = ROOT / '.runlogs/dev-https/mining360-dev.crt.pem'
    key = ROOT / '.runlogs/dev-https/mining360-dev.key.pem'
    commands = [
        ('waitress', ['-m', 'waitress', f'--listen=127.0.0.1:{args.upstream_port}', '--threads=8', 'Mining360IA.wsgi:application']),
        ('codex_worker', [str(ROOT / 'manage.py'), 'run_codex_worker', '--poll-seconds', '0.5']),
    ]
    if certificate.is_file() and key.is_file():
        from deployment.windows.setup_dev_https import certificate_matches
        if certificate_matches(certificate, args.host):
            if controller._listener_pids({args.https_port}):
                raise SystemExit('HTTPS port occupied; existing process preserved.')
            commands.append(('https_gateway', [str(ROOT / 'deployment/windows/https_reverse_proxy.py'),
                '--host', args.host, '--listen', '127.0.0.1', '--port', str(args.https_port),
                '--upstream-port', str(args.upstream_port), '--certificate', str(certificate), '--key', str(key)]))
    stamp = time.strftime('%Y%m%d-%H%M%S')
    children = []
    for name, arguments in commands:
        with (controller.log_directory / f'launcher-{stamp}-{name}.out.log').open('ab') as out, \
             (controller.log_directory / f'launcher-{stamp}-{name}.err.log').open('ab') as err:
            children.append(subprocess.Popen([str(project_python()), *arguments], cwd=ROOT,
                stdout=out, stderr=err, creationflags=subprocess.CREATE_NO_WINDOW))
    time.sleep(2)
    inventory = controller.managed_processes()
    payload = {'schema_version': 2, 'root': str(ROOT), 'machine': socket.gethostname(),
               'environment': 'Development', 'components': [asdict(p) for p in inventory if p.owned]}
    temporary = controller.pid_manifest_path.with_suffix('.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(controller.pid_manifest_path)
    if any(p.poll() is not None for p in children):
        raise SystemExit('A component failed; inspect the component logs before restarting.')
    print('Development started. HTTPS must be verified separately; no DNS or trust changes applied.')


if __name__ == '__main__':
    main()
