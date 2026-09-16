"""Print a sanitized Codex runtime readiness report."""

from __future__ import annotations

import json
from pathlib import Path

from .runtime_probe import CodexRuntimeProbe


def main() -> None:
    result = CodexRuntimeProbe(project_root=Path.cwd()).run().as_dict()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
