from __future__ import annotations

import argparse
import time
from pathlib import Path

from PIL import ImageGrab

from desktop.control_center_models import OperationStep
from desktop.control_center_v2 import Mining360ControlCenterV2
from desktop.control_core import ServiceResult


def capture(state: str, output: Path) -> None:
    app = Mining360ControlCenterV2()
    app.closed = True
    now = time.time()
    results = {}
    for definition in app.registry.services():
        status = "online"
        detail = "Health check completed successfully."
        if state == "degraded" and definition.code == "powerbi":
            status = "offline"
            detail = "Authentication succeeded, but the validation target is unavailable."
        results[definition.code] = ServiceResult(definition.code, definition.name, status, detail, now)
    app._apply_results(results)
    if state == "restarting":
        app.operation_panel.grid(row=3, column=0, sticky="ew", pady=(0, 2))
        app._apply_progress(OperationStep("runtime", "Starting web runtime", 5, 8))
        app._update_action_states(force_disabled=True)
    app.update_idletasks()
    app.update()
    output.parent.mkdir(parents=True, exist_ok=True)
    ImageGrab.grab(window=app.winfo_id()).save(output)
    app._on_close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", choices=("operational", "degraded", "restarting"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    capture(args.state, args.output)


if __name__ == "__main__":
    main()
