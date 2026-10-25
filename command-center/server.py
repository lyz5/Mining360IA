"""Local-only 360 Command Center server.

It reads portfolio metadata and never sends data outside this workstation unless
the operator explicitly confirms a Dropbox documentation sync in the UI.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


APP_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = APP_ROOT.parent
PORTFOLIO_PATH = REPOSITORY_ROOT / "docs" / "PROJECT_PORTFOLIO_2026-10-15.json"
SYNC_MANIFEST_PATH = APP_ROOT / "documentation-sync-manifest.json"
LOCAL_CONFIG_PATH = APP_ROOT / "dropbox-sync.local.json"


def json_response(handler: SimpleHTTPRequestHandler, payload: object, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def git_snapshot(path_text: str | None) -> dict:
    if not path_text:
        return {"available": False}
    path = Path(path_text)
    if not (path / ".git").exists():
        return {"available": False}
    try:
        output = subprocess.run(
            ["git", "-C", str(path), "status", "--short", "--branch"],
            capture_output=True, text=True, timeout=4, check=False,
        ).stdout.splitlines()
        return {"available": True, "branch": output[0].replace("## ", "") if output else "unknown", "changes": max(0, len(output) - 1)}
    except (OSError, subprocess.SubprocessError):
        return {"available": False}


def portfolio_payload() -> dict:
    portfolio = load_json(PORTFOLIO_PATH)
    projects = []
    for project in portfolio["projects"]:
        item = dict(project)
        item["git_live"] = git_snapshot(item.get("canonical_path"))
        memory = REPOSITORY_ROOT / item.get("primary_memory", "")
        item["memory_available"] = memory.exists()
        projects.append(item)
    configured = load_json(LOCAL_CONFIG_PATH) if LOCAL_CONFIG_PATH.exists() else {}
    root = Path(configured.get("dropbox_root", "")) if configured.get("dropbox_root") else None
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "portfolio": {**portfolio, "projects": projects},
        "dropbox": {"configured": bool(root), "available": bool(root and root.is_dir()), "root": str(root) if root else None},
    }


def sync_plan() -> dict:
    manifest = load_json(SYNC_MANIFEST_PATH)
    configured = load_json(LOCAL_CONFIG_PATH) if LOCAL_CONFIG_PATH.exists() else {}
    root = Path(configured.get("dropbox_root", "")) if configured.get("dropbox_root") else None
    files = []
    for relative in manifest["include"]:
        source = REPOSITORY_ROOT / relative
        files.append({"path": relative, "exists": source.is_file(), "sha256": hashlib.sha256(source.read_bytes()).hexdigest() if source.is_file() else None})
    return {"manifest": manifest, "dropbox": {"configured": bool(root), "available": bool(root and root.is_dir()), "root": str(root) if root else None}, "files": files}


def run_sync() -> dict:
    plan = sync_plan()
    if not plan["dropbox"]["available"]:
        raise ValueError("Dropbox Desktop is not configured or its local folder is unavailable.")
    if not all(item["exists"] for item in plan["files"]):
        raise ValueError("A documentation source listed in the manifest is missing.")
    destination_root = Path(plan["dropbox"]["root"]) / plan["manifest"]["destination_folder"]
    copied = []
    for item in plan["files"]:
        source = REPOSITORY_ROOT / item["path"]
        destination = destination_root / item["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        digest = hashlib.sha256(destination.read_bytes()).hexdigest()
        if digest != item["sha256"]:
            raise ValueError(f"Hash verification failed for {item['path']}.")
        copied.append({"path": item["path"], "sha256": digest})
    receipt = {"schema_version": 1, "synchronized_at": datetime.now(timezone.utc).isoformat(), "files": copied}
    (destination_root / "SYNC_RECEIPT.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return receipt


class CommandCenterHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(APP_ROOT), **kwargs)

    def log_message(self, format: str, *args) -> None:
        return

    def do_GET(self) -> None:
        route = urlparse(self.path).path
        if route == "/api/overview":
            return json_response(self, portfolio_payload())
        if route == "/api/sync/plan":
            return json_response(self, sync_plan())
        if route.startswith("/api/projects/"):
            project_id = route.rsplit("/", 1)[-1]
            for project in portfolio_payload()["portfolio"]["projects"]:
                if project["id"] == project_id:
                    return json_response(self, project)
            return json_response(self, {"error": "Project not found."}, HTTPStatus.NOT_FOUND)
        return super().do_GET()

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/api/sync":
            return json_response(self, {"error": "Not found."}, HTTPStatus.NOT_FOUND)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(length) or b"{}")
            if request.get("confirmation") != "SYNC_DOCUMENTATION":
                return json_response(self, {"error": "Explicit confirmation is required."}, HTTPStatus.BAD_REQUEST)
            return json_response(self, run_sync())
        except (ValueError, json.JSONDecodeError) as error:
            return json_response(self, {"error": str(error)}, HTTPStatus.BAD_REQUEST)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 8030), CommandCenterHandler)
    print("360 Command Center: http://127.0.0.1:8030", flush=True)
    server.serve_forever()
