"""Stop only the preview processes recorded by the local launcher."""
import argparse
import json
import os
from datetime import datetime
from pathlib import Path
import psutil


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-directory', required=True, type=Path)
    args=parser.parse_args()
    state=args.state_directory.resolve()
    marker=state/'runtime-process.json'
    manifest=json.loads(marker.read_text(encoding='utf-8-sig'))
    if Path(manifest['state_root']).resolve()!=state:
        raise SystemExit('Preview identity does not match.')
    script=Path(__file__).with_name('local_preview.py').resolve()
    if Path(manifest['app_root']).resolve()!=script.parents[1]:
        raise SystemExit('Preview source identity does not match.')
    try:
        process=psutil.Process(manifest['pid'])
    except psutil.NoSuchProcess:
        print('The recorded preview process has already stopped.')
        return
    created=datetime.fromisoformat(manifest['created_utc'].replace('Z','+00:00')).timestamp()
    if abs(process.create_time()-created)>2:
        raise SystemExit('PID was reused. No process was stopped.')
    targets=[]
    for target in [*process.children(recursive=True),process]:
        # Start-Process -WindowStyle Hidden also creates a Windows console host.
        # Recognize that direct child, leave it to Windows, and stop only Python.
        console=Path(os.environ['SystemRoot'])/'System32/conhost.exe'
        if (target.pid!=process.pid and target.ppid()==process.pid
                and Path(target.exe()).resolve()==console.resolve()
                and 0<=target.create_time()-process.create_time()<2):
            continue
        command=target.cmdline()
        paths=[Path(value).resolve() for value in command if value.lower().endswith('local_preview.py')]
        if paths!=[script] or '--state-directory' not in command or Path(command[command.index('--state-directory')+1]).resolve()!=state:
            raise SystemExit('Unrecognized child process. No process was stopped.')
        targets.append(target)
    for target in targets:
        try:target.terminate()
        except psutil.NoSuchProcess:pass
    _,remaining=psutil.wait_procs(targets,timeout=10)
    if remaining:
        raise SystemExit('A preview process is still stopping. No unrelated process was touched.')
    print('Isolated local preview stopped. BODEFM was not contacted.')


if __name__=='__main__':main()
