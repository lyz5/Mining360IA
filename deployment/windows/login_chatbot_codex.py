"""Interactive login for the configured application identity, not the personal profile."""
import argparse
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root))
    from desktop.project_environment import configure
    configure()
    import django
    django.setup()
    from django.conf import settings
    from codex_chatbot.orchestrator import _resolve_codex_cli_path
    cli = _resolve_codex_cli_path()
    home = Path(settings.CODEX_CHATBOT_HOME).resolve()
    if args.check_only:
        print("Application Python and Chatbot runtime resolved. No authentication attempted.")
        return 0
    environment = os.environ.copy()
    environment["CODEX_HOME"] = str(home)
    return subprocess.run([cli, "login"], cwd=root, env=environment, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
