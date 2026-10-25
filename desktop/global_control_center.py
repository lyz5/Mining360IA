"""360 Global Command Center — local, portfolio-wide desktop application."""
from __future__ import annotations

import hashlib
import json
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import messagebox, ttk

from desktop.control_center_event_store import ControlCenterEventStore


ROOT = Path(__file__).resolve().parents[1]
PORTFOLIO_PATH = ROOT / "docs" / "PROJECT_PORTFOLIO_2026-10-15.json"
COMMAND_CENTER = ROOT / "command-center"
COLORS = {"background":"#070D1B","surface":"#0E172A","high":"#131F36","hover":"#182640","navy":"#081126","text":"#F7F9FC","muted":"#91A0B8","border":"#24324B","yellow":"#FFD400","green":"#29C887","amber":"#F5A524","red":"#F05252","blue":"#4E8CF5","gray":"#70819C"}


def project_state(project: dict) -> tuple[str, str]:
    content = " ".join(str(project.get(key, "")) for key in ("status", "git_status", "production_maintenance_status")).casefold()
    if "pending" in content or "à confirmer" in content:
        return "PENDING", COLORS["amber"]
    if any(value in content for value in ("active", "opérationnel", "verified")):
        return "OPERATIONAL", COLORS["green"]
    return "TRACKED", COLORS["gray"]


def documentation_sync_status(dropbox_root: Path | None) -> dict:
    """Check only the approved documentation mirror and its hash receipt.

    Dropbox Desktop exposes no reliable cloud-completion API here. This is a
    local-copy and hash check; Dropbox Desktop remains the cloud-sync authority.
    """
    if not dropbox_root or not dropbox_root.is_dir():
        return {"state": "NOT CONFIGURED", "files": 0, "expected": 0,
                "last_sync": "No receipt", "detail": "Configure Dropbox first."}
    try:
        manifest = json.loads((COMMAND_CENTER / "documentation-sync-manifest.json").read_text(encoding="utf-8"))
        destination = dropbox_root / manifest["destination_folder"]
        expected = list(manifest["include"])
        for directory_rule in manifest.get("include_directories", []):
            source_directory = ROOT / directory_rule["path"]
            extensions = {extension.casefold() for extension in directory_rule["extensions"]}
            expected.extend(
                str(source.relative_to(ROOT))
                for source in source_directory.rglob("*")
                if source.is_file() and source.suffix.casefold() in extensions
            )
        portfolio = json.loads(PORTFOLIO_PATH.read_text(encoding="utf-8"))
        project_roots = {project["id"]: Path(project.get("canonical_path", "")) for project in portfolio["projects"]}
        for project_rule in manifest.get("external_projects", []):
            project_root = project_roots.get(project_rule["id"])
            if project_root and project_root.is_dir():
                expected.extend(
                    str(Path("projects") / project_rule["id"] / relative_path)
                    for relative_path in project_rule["include"]
                )
        expected = sorted(set(expected))
        receipt_path = destination / "SYNC_RECEIPT.json"
        status = {"state": "NOT SYNCHRONIZED", "files": 0, "expected": len(expected),
                  "last_sync": "No receipt", "detail": "Run the approved documentation sync."}
        if not receipt_path.is_file():
            return status
        receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
        recorded = {item.get("RelativePath"): item.get("SHA256") for item in receipt.get("files", [])}
        verified = 0
        for relative_path in expected:
            copied = destination / relative_path
            expected_hash = recorded.get(relative_path)
            if copied.is_file() and expected_hash:
                actual_hash = hashlib.sha256(copied.read_bytes()).hexdigest().upper()
                verified += actual_hash == expected_hash.upper()
        status.update({"files": verified, "last_sync": receipt.get("synchronized_at", "Unknown")})
        if verified == len(expected) and set(recorded) == set(expected):
            status.update({"state": "LOCALLY VERIFIED", "detail": "Copies and hashes match. Confirm cloud completion in Dropbox Desktop."})
        else:
            status.update({"state": "ATTENTION", "detail": "Local mirror and receipt differ. Run synchronization again."})
        return status
    except (OSError, ValueError, KeyError, TypeError) as error:
        return {"state": "CHECK FAILED", "files": 0, "expected": 0,
                "last_sync": "Unavailable", "detail": f"Cannot read sync evidence: {error}"}


class ProjectCard(tk.Frame):
    def __init__(self, master, project: dict, select) -> None:
        super().__init__(master, bg=COLORS["surface"], highlightthickness=1, highlightbackground=COLORS["border"], cursor="hand2")
        self.project = project
        label, color = project_state(project)
        tk.Frame(self, bg=color, width=4).pack(side="left", fill="y")
        body = tk.Frame(self, bg=COLORS["surface"]); body.pack(fill="both", expand=True, padx=14, pady=12)
        top = tk.Frame(body, bg=COLORS["surface"]); top.pack(fill="x")
        tk.Label(top, text=project["name"], bg=COLORS["surface"], fg=COLORS["text"], font=("Segoe UI Semibold", 11)).pack(side="left")
        tk.Label(top, text=label, bg=COLORS["surface_high"], fg=color, font=("Segoe UI Semibold", 8), padx=6, pady=2).pack(side="right")
        detail = project.get("status") or project.get("git_status") or project.get("production_maintenance_status") or "Project state recorded in portfolio memory."
        tk.Label(body, text=detail[:150], bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI", 8), justify="left", wraplength=245, anchor="w").pack(fill="x", pady=(7, 8))
        tk.Label(body, text=project.get("primary_memory", "Portfolio register"), bg=COLORS["surface"], fg=COLORS["yellow"], font=("Segoe UI", 8), anchor="w").pack(fill="x")
        for widget in (self, body, top):
            widget.bind("<Button-1>", lambda _event: select(project))


class GlobalControlCenter(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("360 Global Command Center")
        self.geometry(f"{min(1360, max(1040, self.winfo_screenwidth()-48))}x{min(840, max(660, self.winfo_screenheight()-88))}")
        self.minsize(1000, 650); self.configure(bg=COLORS["background"])
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="360-global-control")
        self.event_store = ControlCenterEventStore(ROOT / ".runlogs" / "global-control-center")
        self.portfolio: dict = {}; self.projects: list[dict] = []; self.current_view = "Overview"; self.closed = False
        self._style(); self._build(); self.protocol("WM_DELETE_WINDOW", self._close); self.after(100, self._drain); self.after(200, self.refresh); self.after(1000, self._clock)

    def _style(self) -> None:
        style = ttk.Style(self); style.theme_use("clam")
        style.configure("Primary.TButton", background=COLORS["yellow"], foreground=COLORS["navy"], bordercolor=COLORS["yellow"], padding=(14,9), font=("Segoe UI Semibold",9))
        style.configure("Secondary.TButton", background=COLORS["high"], foreground=COLORS["text"], bordercolor=COLORS["border"], padding=(13,9), font=("Segoe UI Semibold",9))

    def _build(self) -> None:
        header = tk.Frame(self, bg=COLORS["navy"], height=104); header.pack(fill="x"); header.pack_propagate(False)
        brand = tk.Frame(header, bg=COLORS["navy"]); brand.pack(side="left", padx=26, pady=19)
        tk.Label(brand,text="360",bg=COLORS["yellow"],fg=COLORS["navy"],font=("Segoe UI Black",12),padx=10,pady=8).pack(side="left",padx=(0,14))
        titles = tk.Frame(brand,bg=COLORS["navy"]); titles.pack(side="left")
        tk.Label(titles,text="360 Global Command Center",bg=COLORS["navy"],fg=COLORS["text"],font=("Segoe UI Semibold",20)).pack(anchor="w")
        tk.Label(titles,text="Portfolio, continuity and documentation management",bg=COLORS["navy"],fg=COLORS["muted"],font=("Segoe UI",9)).pack(anchor="w",pady=(2,0))
        self.clock_label=tk.Label(header,bg=COLORS["navy"],fg=COLORS["text"],font=("Segoe UI Semibold",10)); self.clock_label.pack(side="right",padx=26,pady=20,anchor="n")
        shell=tk.Frame(self,bg=COLORS["background"]); shell.pack(fill="both",expand=True,padx=22,pady=(14,16)); shell.columnconfigure(0,weight=1); shell.rowconfigure(4,weight=1)
        self._summary(shell); self._toolbar(shell); self._navigation(shell); self._workspace(shell); self._footer()

    def _summary(self, parent) -> None:
        summary=tk.Frame(parent,bg=COLORS["surface"],highlightthickness=1,highlightbackground=COLORS["border"]); summary.grid(row=0,column=0,sticky="ew")
        self.summary={}; fields=(("projects","PROJECTS","—"),("operational","OPERATIONAL","—"),("attention","ATTENTION","—"),("memory","MEMORIES","—"),("dropbox","DROPBOX","Checking"),("checked","LAST CHECK","Waiting"))
        for index,(code,label,value) in enumerate(fields):
            summary.columnconfigure(index,weight=1,uniform="summary"); cell=tk.Frame(summary,bg=COLORS["surface"]); cell.grid(row=0,column=index,sticky="nsew",padx=1,pady=11)
            if index: tk.Frame(cell,width=1,bg=COLORS["border"]).pack(side="left",fill="y",padx=(0,12))
            box=tk.Frame(cell,bg=COLORS["surface"]); box.pack(side="left",fill="both",expand=True)
            tk.Label(box,text=label,bg=COLORS["surface"],fg=COLORS["muted"],font=("Segoe UI Semibold",7)).pack(anchor="w")
            value_label=tk.Label(box,text=value,bg=COLORS["surface"],fg=COLORS["text"],font=("Segoe UI Semibold",11)); value_label.pack(anchor="w",pady=(3,0)); self.summary[code]=value_label

    def _toolbar(self, parent) -> None:
        bar=tk.Frame(parent,bg=COLORS["background"]); bar.grid(row=1,column=0,sticky="ew",pady=12)
        ttk.Button(bar,text="Actualiser",style="Primary.TButton",command=self.refresh).pack(side="left")
        ttk.Button(bar,text="Ouvrir le portfolio",style="Secondary.TButton",command=lambda:self._change_view("Projects")).pack(side="left",padx=(8,0))
        ttk.Button(bar,text="Dropbox",style="Secondary.TButton",command=lambda:self._change_view("Memory & Dropbox")).pack(side="left",padx=(8,0))
        ttk.Button(bar,text="Ouvrir la mémoire",style="Secondary.TButton",command=self._open_memory).pack(side="right")

    def _navigation(self, parent) -> None:
        nav=tk.Frame(parent,bg=COLORS["surface"],height=40); nav.grid(row=2,column=0,sticky="ew"); nav.pack_propagate(False); self.nav={}
        for name in ("Overview","Projects","Memory & Dropbox","Activity"):
            button=tk.Button(nav,text=name,command=lambda value=name:self._change_view(value),bg=COLORS["surface"],fg=COLORS["text"] if name=="Overview" else COLORS["muted"],activebackground=COLORS["hover"],activeforeground=COLORS["text"],relief="flat",bd=0,padx=15,font=("Segoe UI Semibold",9),cursor="hand2"); button.pack(side="left",fill="y"); self.nav[name]=button

    def _workspace(self, parent) -> None:
        self.workspace=tk.Frame(parent,bg=COLORS["background"]); self.workspace.grid(row=4,column=0,sticky="nsew",pady=(12,0)); self.workspace.columnconfigure(0,weight=1); self.workspace.rowconfigure(1,weight=1)
        head=tk.Frame(self.workspace,bg=COLORS["background"]); head.grid(row=0,column=0,sticky="ew",pady=(0,8)); self.workspace_title=tk.Label(head,text="Portfolio Services",bg=COLORS["background"],fg=COLORS["text"],font=("Segoe UI Semibold",13)); self.workspace_title.pack(side="left"); self.workspace_hint=tk.Label(head,text="Select a project for recorded evidence.",bg=COLORS["background"],fg=COLORS["muted"],font=("Segoe UI",8)); self.workspace_hint.pack(side="right")
        self.canvas=tk.Canvas(self.workspace,bg=COLORS["background"],highlightthickness=0); self.canvas.grid(row=1,column=0,sticky="nsew"); scroll=ttk.Scrollbar(self.workspace,orient="vertical",command=self.canvas.yview); scroll.grid(row=1,column=1,sticky="ns"); self.canvas.configure(yscrollcommand=scroll.set); self.content=tk.Frame(self.canvas,bg=COLORS["background"]); self.window=self.canvas.create_window((0,0),window=self.content,anchor="nw"); self.content.bind("<Configure>",lambda _e:self.canvas.configure(scrollregion=self.canvas.bbox("all"))); self.canvas.bind("<Configure>",lambda e:self.canvas.itemconfigure(self.window,width=e.width))

    def _footer(self) -> None:
        self.footer=tk.Label(self,text="Loading portfolio register…",bg=COLORS["navy"],fg=COLORS["muted"],font=("Segoe UI",8),anchor="w",padx=22,pady=8); self.footer.pack(fill="x",side="bottom")

    def refresh(self) -> None:
        self.footer.configure(text="Refreshing portfolio evidence…"); future=self.executor.submit(self._load_portfolio); future.add_done_callback(lambda task:self.events.put(("portfolio", task)))

    def _load_portfolio(self) -> dict:
        payload=json.loads(PORTFOLIO_PATH.read_text(encoding="utf-8")); config=COMMAND_CENTER / "dropbox-sync.local.json"; dropbox=False
        if config.exists():
            try: dropbox=Path(json.loads(config.read_text(encoding="utf-8")).get("dropbox_root","")).is_dir()
            except (OSError,json.JSONDecodeError): pass
        for project in payload["projects"]:
            path=Path(project.get("canonical_path", "")); project["git"]="Not inspected"
            if (path/".git").exists():
                try:
                    lines=subprocess.run(["git","-C",str(path),"status","--short","--branch"],capture_output=True,text=True,timeout=4).stdout.splitlines()
                    project["git"]=lines[0].replace("## ","") if lines else "No Git status returned"
                except (OSError,subprocess.SubprocessError): project["git"]="Unavailable"
            project["memory_available"]=(ROOT/project.get("primary_memory","")).exists()
        dropbox_root = None
        if dropbox:
            try:
                dropbox_root = Path(json.loads(config.read_text(encoding="utf-8")).get("dropbox_root", ""))
            except (OSError, json.JSONDecodeError):
                pass
        return {"portfolio":payload,"dropbox":dropbox,"sync_status":documentation_sync_status(dropbox_root)}

    def _render(self) -> None:
        for child in self.content.winfo_children(): child.destroy()
        title_hint={"Overview":("Portfolio Services","Select a project for recorded evidence."),"Projects":("Projects & Environments","Read-only local inventory."),"Memory & Dropbox":("Documentation & Dropbox","Explicit confirmation is required to copy files."),"Activity":("Activity & Evidence","Local observations only.")}[self.current_view]
        self.workspace_title.configure(text=title_hint[0]); self.workspace_hint.configure(text=title_hint[1])
        if self.current_view in {"Overview","Projects"}: self._render_projects()
        elif self.current_view=="Memory & Dropbox": self._render_memory()
        else: self._render_activity()

    def _render_projects(self) -> None:
        for index,project in enumerate(self.projects):
            self.content.columnconfigure(index%3,weight=1,uniform="cards"); card=ProjectCard(self.content,project,self._show_project); card.grid(row=index//3,column=index%3,sticky="nsew",padx=(0 if index%3==0 else 7,0),pady=(0,7))

    def _render_memory(self) -> None:
        manifest=json.loads((COMMAND_CENTER/"documentation-sync-manifest.json").read_text(encoding="utf-8")); box=tk.Frame(self.content,bg=COLORS["surface"],highlightthickness=1,highlightbackground=COLORS["border"]); box.pack(fill="both",expand=True)
        tk.Label(box,text="Authorized documentation sync",bg=COLORS["surface"],fg=COLORS["text"],font=("Segoe UI Semibold",14)).pack(anchor="w",padx=18,pady=(18,4)); tk.Label(box,text="Only this allowlist can be copied. Neemba data, secrets, databases, media and exports remain excluded.",bg=COLORS["surface"],fg=COLORS["muted"],font=("Segoe UI",9)).pack(anchor="w",padx=18)
        sync=getattr(self,"sync_status",{"state":"Checking","files":0,"expected":0,"last_sync":"Waiting","detail":"Refreshing..."})
        color=COLORS["green"] if sync["state"]=="LOCALLY VERIFIED" else COLORS["amber"]
        status_box=tk.Frame(box,bg=COLORS["high"]); status_box.pack(fill="x",padx=18,pady=(16,8))
        tk.Label(status_box,text=f"{sync['state']}  ·  {sync['files']}/{sync['expected']} files",bg=COLORS["high"],fg=color,font=("Segoe UI Semibold",11)).pack(anchor="w",padx=12,pady=(10,2))
        tk.Label(status_box,text=f"Last local sync: {sync['last_sync']}\n{sync['detail']}",bg=COLORS["high"],fg=COLORS["muted"],font=("Segoe UI",8),justify="left").pack(anchor="w",padx=12,pady=(0,10))
        for item in manifest["include"]: tk.Label(box,text=f"✓  {item}",bg=COLORS["surface"],fg=COLORS["text"],font=("Cascadia Mono",9)).pack(anchor="w",padx=22,pady=(8 if item==manifest['include'][0] else 2,0))
        for directory_rule in manifest.get("include_directories",[]): tk.Label(box,text=f"✓  {directory_rule['path']}/** ({', '.join(directory_rule['extensions'])})",bg=COLORS["surface"],fg=COLORS["yellow"],font=("Cascadia Mono",9)).pack(anchor="w",padx=22,pady=(8,0))
        for project_rule in manifest.get("external_projects",[]): tk.Label(box,text=f"✓  projects/{project_rule['id']} ({len(project_rule['include'])} reviewed docs)",bg=COLORS["surface"],fg=COLORS["yellow"],font=("Cascadia Mono",9)).pack(anchor="w",padx=22,pady=(8,0))
        state="Dropbox ready" if self.dropbox else "Dropbox not configured"; tk.Label(box,text=state,bg=COLORS["surface"],fg=COLORS["green"] if self.dropbox else COLORS["amber"],font=("Segoe UI Semibold",10)).pack(anchor="w",padx=18,pady=(20,4))
        ttk.Button(box,text="Synchroniser la documentation",style="Primary.TButton",command=self._confirm_sync,state="normal" if self.dropbox else "disabled").pack(anchor="w",padx=18,pady=(4,18))

    def _render_activity(self) -> None:
        box=tk.Text(self.content,bg="#091222",fg="#B9C6D9",relief="flat",font=("Cascadia Mono",9),padx=14,pady=14,wrap="word"); box.pack(fill="both",expand=True)
        box.insert("end",f"{time.strftime('%H:%M:%S')}  INFO       360 Global Command Center ready\n")
        sync=getattr(self,"sync_status",{})
        box.insert("end",f"{time.strftime('%H:%M:%S')}  DROPBOX    {sync.get('state','Checking')} {sync.get('files',0)}/{sync.get('expected',0)} documentation files\n")
        for project in self.projects: box.insert("end",f"{time.strftime('%H:%M:%S')}  PORTFOLIO  {project['name']}: {project.get('git','Not inspected')}\n")
        box.configure(state="disabled")

    def _show_project(self, project: dict) -> None:
        dialog=tk.Toplevel(self); dialog.title(project["name"]); dialog.configure(bg=COLORS["surface"]); dialog.geometry("620x470"); dialog.transient(self)
        tk.Label(dialog,text=project["name"],bg=COLORS["navy"],fg=COLORS["text"],font=("Segoe UI Semibold",17),padx=20,pady=16).pack(fill="x")
        text_box=tk.Text(dialog,bg=COLORS["surface"],fg=COLORS["text"],relief="flat",font=("Segoe UI",10),padx=20,pady=18,wrap="word"); text_box.pack(fill="both",expand=True)
        for label,value in (("Status",project.get("status") or project.get("git_status") or project.get("production_maintenance_status")),("Local",project.get("local_url") or project.get("canonical_path")),("Production",project.get("production_url") or project.get("remote_environment")),("Memory",project.get("primary_memory")),("Git",project.get("git"))): text_box.insert("end",f"{label}\n{value or '—'}\n\n")
        text_box.configure(state="disabled")

    def _confirm_sync(self) -> None:
        if not messagebox.askokcancel("Synchroniser la documentation","Copier uniquement les fichiers du manifeste autorisé vers Dropbox ?\n\nAucune suppression ne sera effectuée.",parent=self): return
        config=json.loads((COMMAND_CENTER/"dropbox-sync.local.json").read_text(encoding="utf-8")); command=["powershell","-NoProfile","-ExecutionPolicy","Bypass","-File",str(COMMAND_CENTER/"sync-documentation-to-dropbox.ps1"),"-DropboxRoot",config["dropbox_root"],"-Execute"]
        future=self.executor.submit(subprocess.run,command,capture_output=True,text=True,timeout=120); future.add_done_callback(lambda task:self.events.put(("sync",task)))

    def _open_memory(self) -> None:
        import os; os.startfile(ROOT/"docs"/"PROJECT_PORTFOLIO_MEMORY_2026-10-15.md")

    def _change_view(self, name: str) -> None:
        self.current_view=name
        for key,button in self.nav.items(): button.configure(fg=COLORS["text"] if key==name else COLORS["muted"])
        self._render()

    def _drain(self) -> None:
        try:
            while True:
                kind,payload=self.events.get_nowait()
                try: value=payload.result()
                except Exception as error: value=error
                if kind=="portfolio":
                    if isinstance(value,Exception): self.footer.configure(text=f"Portfolio refresh failed: {value}")
                    else:
                        self.portfolio=value["portfolio"]; self.projects=self.portfolio["projects"]; self.dropbox=value["dropbox"]; self.sync_status=value["sync_status"]; operational=sum(project_state(p)[0]=="OPERATIONAL" for p in self.projects); pending=sum(project_state(p)[0]=="PENDING" for p in self.projects); memories=sum(p["memory_available"] for p in self.projects)
                        sync_text=f"{self.sync_status['files']}/{self.sync_status['expected']} verified" if self.sync_status["state"]=="LOCALLY VERIFIED" else self.sync_status["state"]
                        sync_color=COLORS["green"] if self.sync_status["state"]=="LOCALLY VERIFIED" else COLORS["amber"]
                        self.summary["projects"].configure(text=str(len(self.projects))); self.summary["operational"].configure(text=str(operational),fg=COLORS["green"]); self.summary["attention"].configure(text=str(pending),fg=COLORS["amber"]); self.summary["memory"].configure(text=str(memories)); self.summary["dropbox"].configure(text=sync_text,fg=sync_color); self.summary["checked"].configure(text=time.strftime("%H:%M:%S")); self.footer.configure(text=f"Portfolio register {self.portfolio.get('as_of','—')} · {len(self.projects)} projects · local-only"); self._render()
                elif kind=="sync":
                    if isinstance(value,Exception) or value.returncode: messagebox.showerror("Dropbox sync",str(value) if isinstance(value,Exception) else value.stderr,parent=self)
                    else: messagebox.showinfo("Dropbox sync","Documentation synchronized and hash-verified.",parent=self); self.event_store.append({"type":"dropbox_sync","status":"completed"}); self.refresh()
        except queue.Empty: pass
        if not self.closed: self.after(100,self._drain)

    def _clock(self) -> None:
        if self.closed:return
        self.clock_label.configure(text=time.strftime("%d %b %Y · %H:%M:%S")); self.after(1000,self._clock)

    def _close(self) -> None:
        self.closed=True; self.executor.shutdown(wait=False,cancel_futures=True); self.destroy()


def main() -> None:
    GlobalControlCenter().mainloop()


if __name__ == "__main__": main()
