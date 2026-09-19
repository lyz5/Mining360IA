from __future__ import annotations

import getpass
import ctypes
import os
import queue
import threading
import time
import tkinter as tk
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from tkinter import messagebox, ttk

from desktop.control_center_event_store import ControlCenterEventStore
from desktop.control_center_models import OperationResult, OperationStatus, OperationStep
from desktop.control_core import Mining360Controller, ServiceResult
from desktop.extended_health import ExtendedHealthChecker
from desktop.service_lifecycle_manager import OperationInProgressError, ServiceLifecycleManager
from desktop.service_registry import ServiceDefinition, ServiceRegistry


COLORS = {
    "background": "#070D1B",
    "surface": "#0E172A",
    "surface_high": "#131F36",
    "surface_hover": "#182640",
    "navy": "#081126",
    "text": "#F7F9FC",
    "muted": "#91A0B8",
    "border": "#24324B",
    "yellow": "#FFD400",
    "yellow_hover": "#E7C000",
    "green": "#29C887",
    "amber": "#F5A524",
    "red": "#F05252",
    "blue": "#4E8CF5",
    "gray": "#70819C",
}

STATUS_META = {
    "online": ("Operational", COLORS["green"]),
    "degraded": ("Degraded", COLORS["amber"]),
    "offline": ("Unavailable", COLORS["red"]),
    "starting": ("Starting", COLORS["blue"]),
    "stopping": ("Stopping", COLORS["blue"]),
    "restarting": ("Restarting", COLORS["blue"]),
    "not_configured": ("Not configured", COLORS["gray"]),
    "expired": ("Check expired", COLORS["amber"]),
    "unknown": ("Unknown", COLORS["gray"]),
}


class ServiceCard(tk.Frame):
    def __init__(self, master, definition: ServiceDefinition, command) -> None:
        super().__init__(
            master,
            bg=COLORS["surface"],
            highlightthickness=1,
            highlightbackground=COLORS["border"],
            cursor="hand2",
        )
        self.definition = definition
        self.command = command
        self.result: ServiceResult | None = None
        self.columnconfigure(2, weight=1)
        self.status_bar = tk.Frame(self, width=3, bg=COLORS["gray"])
        self.status_bar.grid(row=0, column=0, rowspan=4, sticky="ns")
        self.dot = tk.Canvas(self, width=18, height=18, bg=COLORS["surface"], highlightthickness=0)
        self.dot.grid(row=0, column=1, padx=(16, 8), pady=(15, 0), sticky="nw")
        self.dot_id = self.dot.create_oval(4, 4, 14, 14, fill=COLORS["gray"], outline="")
        self.name = tk.Label(
            self, text=definition.name, bg=COLORS["surface"], fg=COLORS["text"],
            font=("Segoe UI Semibold", 11), anchor="w",
        )
        self.name.grid(row=0, column=2, padx=(0, 14), pady=(13, 0), sticky="ew")
        self.status = tk.Label(
            self, text="Checking", bg=COLORS["surface"], fg=COLORS["gray"],
            font=("Segoe UI Semibold", 9), anchor="w",
        )
        self.status.grid(row=1, column=1, columnspan=2, padx=(16, 14), pady=(5, 0), sticky="ew")
        self.detail = tk.Label(
            self, text="Waiting for health evidence.", bg=COLORS["surface"], fg=COLORS["muted"],
            font=("Segoe UI", 9), anchor="w", justify="left", wraplength=190,
        )
        self.detail.grid(row=2, column=1, columnspan=2, padx=(16, 14), pady=(4, 0), sticky="ew")
        self.checked = tk.Label(
            self, text="Not evaluated", bg=COLORS["surface"], fg=COLORS["gray"],
            font=("Segoe UI", 8), anchor="w",
        )
        self.checked.grid(row=3, column=1, columnspan=2, padx=(16, 14), pady=(5, 13), sticky="ew")
        for widget in (self, self.dot, self.name, self.status, self.detail, self.checked):
            widget.bind("<Button-1>", self._selected)
            widget.bind("<Enter>", self._enter)
            widget.bind("<Leave>", self._leave)

    def set_result(self, result: ServiceResult) -> None:
        self.result = result
        status_text, color = STATUS_META.get(result.status, STATUS_META["unknown"])
        self.status.configure(text=status_text, fg=color)
        self.detail.configure(text=_friendly_detail(result))
        self.checked.configure(text=f"Checked {time.strftime('%H:%M:%S', time.localtime(result.checked_at))}")
        self.dot.itemconfigure(self.dot_id, fill=color)
        self.status_bar.configure(bg=color)

    def _selected(self, _event=None) -> None:
        self.command(self.definition.code)

    def _enter(self, _event=None) -> None:
        for widget in (self, self.dot, self.name, self.status, self.detail, self.checked):
            widget.configure(bg=COLORS["surface_hover"])

    def _leave(self, _event=None) -> None:
        for widget in (self, self.dot, self.name, self.status, self.detail, self.checked):
            widget.configure(bg=COLORS["surface"])


class Mining360ControlCenterV2(tk.Tk):
    FAST_REFRESH_MS = 5000
    MEDIUM_REFRESH_MS = 12000
    SLOW_REFRESH_MS = 60000

    def __init__(self) -> None:
        super().__init__()
        self.title("Mining 360 Control Center V2")
        width = min(1360, max(1040, self.winfo_screenwidth() - 48))
        height = min(840, max(660, self.winfo_screenheight() - 88))
        self.geometry(f"{width}x{height}")
        self.minsize(1000, 650)
        self.configure(bg=COLORS["background"])
        self.controller = Mining360Controller()
        self.registry = ServiceRegistry()
        self.definitions = self.registry.by_code()
        self.event_store = ControlCenterEventStore(self.controller.log_directory)
        self.extended_health = ExtendedHealthChecker(self.controller.root)
        self.lifecycle = ServiceLifecycleManager(self.controller, self.registry, self.event_store)
        self.executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix="mining360-control-v2")
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.results: dict[str, ServiceResult] = {}
        self.cards: dict[str, ServiceCard] = {}
        self.selected_service = "django"
        self.current_view = "Overview"
        self.operation_result: OperationResult | None = None
        self.checks_running: set[str] = set()
        self.closed = False
        self._configure_styles()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._drain_events)
        self.after(250, self._refresh_fast)
        self.after(500, self._refresh_medium)
        self.after(800, self._refresh_slow)
        self.after(1000, self._update_clock)

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "Primary.TButton", background=COLORS["yellow"], foreground="#071020",
            bordercolor=COLORS["yellow"], padding=(16, 9), font=("Segoe UI Semibold", 9),
        )
        style.map("Primary.TButton", background=[("active", COLORS["yellow_hover"]), ("disabled", "#3A4150")])
        style.configure(
            "Secondary.TButton", background=COLORS["surface_high"], foreground=COLORS["text"],
            bordercolor=COLORS["border"], padding=(14, 9), font=("Segoe UI Semibold", 9),
        )
        style.map("Secondary.TButton", background=[("active", COLORS["surface_hover"]), ("disabled", COLORS["surface"])])
        style.configure(
            "Restart.TButton", background=COLORS["surface"], foreground=COLORS["yellow"],
            bordercolor=COLORS["yellow"], padding=(16, 9), font=("Segoe UI Semibold", 9),
        )
        style.map("Restart.TButton", background=[("active", "#293019"), ("disabled", COLORS["surface"])])
        style.configure(
            "Danger.TButton", background=COLORS["surface"], foreground="#FF8585",
            bordercolor="#71333B", padding=(16, 9), font=("Segoe UI Semibold", 9),
        )
        style.map("Danger.TButton", background=[("active", "#2D1820"), ("disabled", COLORS["surface"])])
        style.configure(
            "Horizontal.TProgressbar", troughcolor=COLORS["surface"], background=COLORS["yellow"],
            bordercolor=COLORS["surface"], lightcolor=COLORS["yellow"], darkcolor=COLORS["yellow"],
        )

    def _build_ui(self) -> None:
        self._build_header()
        shell = tk.Frame(self, bg=COLORS["background"])
        shell.pack(fill="both", expand=True, padx=22, pady=(14, 16))
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(4, weight=1)
        self._build_summary(shell)
        self._build_toolbar(shell)
        self._build_navigation(shell)
        self._build_operation_panel(shell)
        self._build_workspace(shell)
        self._build_footer()

    def _build_header(self) -> None:
        header = tk.Frame(self, bg=COLORS["navy"], height=104)
        header.pack(fill="x")
        header.pack_propagate(False)
        brand = tk.Frame(header, bg=COLORS["navy"])
        brand.pack(side="left", fill="y", padx=26, pady=19)
        tk.Label(
            brand, text="M360", bg=COLORS["yellow"], fg="#071020",
            font=("Segoe UI Black", 12), padx=10, pady=8,
        ).pack(side="left", padx=(0, 14))
        titles = tk.Frame(brand, bg=COLORS["navy"])
        titles.pack(side="left")
        tk.Label(
            titles, text="Mining 360 Control Center", bg=COLORS["navy"], fg=COLORS["text"],
            font=("Segoe UI Semibold", 20),
        ).pack(anchor="w")
        tk.Label(
            titles, text="Service and connectivity management", bg=COLORS["navy"],
            fg=COLORS["muted"], font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(2, 0))
        metadata = tk.Frame(header, bg=COLORS["navy"])
        metadata.pack(side="right", fill="y", padx=26, pady=17)
        self.clock_label = tk.Label(metadata, bg=COLORS["navy"], fg=COLORS["text"], font=("Segoe UI Semibold", 10))
        self.clock_label.pack(anchor="e")
        tk.Label(
            metadata, text=f"{getpass.getuser()} · {_windows_authorization_label()}", bg=COLORS["navy"],
            fg=COLORS["muted"], font=("Segoe UI", 8),
        ).pack(anchor="e", pady=(4, 0))
        env_color = COLORS["red"] if self.registry.environment.casefold() == "production" else COLORS["blue"]
        tk.Label(
            metadata, text=self.registry.environment.upper(), bg=env_color, fg="white",
            font=("Segoe UI Semibold", 8), padx=9, pady=3,
        ).pack(anchor="e", pady=(8, 0))

    def _build_summary(self, parent) -> None:
        summary = tk.Frame(parent, bg=COLORS["surface"], highlightthickness=1, highlightbackground=COLORS["border"])
        summary.grid(row=0, column=0, sticky="ew")
        for column in range(6):
            summary.columnconfigure(column, weight=1, uniform="summary")
        fields = (
            ("global", "SYSTEM STATUS", "Checking"),
            ("operational", "OPERATIONAL", "0 / 7"),
            ("degraded", "DEGRADED", "Not Evaluated"),
            ("incidents", "INCIDENTS", "Not Evaluated"),
            ("jobs", "PENDING JOBS", "Not Evaluated"),
            ("checked", "LAST CHECK", "Waiting"),
        )
        self.summary_values = {}
        for index, (code, label, value) in enumerate(fields):
            cell = tk.Frame(summary, bg=COLORS["surface"])
            cell.grid(row=0, column=index, sticky="nsew", padx=1, pady=11)
            if index:
                tk.Frame(cell, width=1, bg=COLORS["border"]).pack(side="left", fill="y", padx=(0, 13))
            box = tk.Frame(cell, bg=COLORS["surface"])
            box.pack(side="left", fill="both", expand=True)
            tk.Label(box, text=label, bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI Semibold", 7)).pack(anchor="w")
            item = tk.Label(box, text=value, bg=COLORS["surface"], fg=COLORS["text"], font=("Segoe UI Semibold", 11))
            item.pack(anchor="w", pady=(3, 0))
            self.summary_values[code] = item

    def _build_toolbar(self, parent) -> None:
        bar = tk.Frame(parent, bg=COLORS["background"])
        bar.grid(row=1, column=0, sticky="ew", pady=12)
        self.start_button = ttk.Button(bar, text="Start", style="Primary.TButton", command=lambda: self._run_lifecycle("start"))
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(bar, text="Stop", style="Danger.TButton", command=lambda: self._run_lifecycle("stop"))
        self.stop_button.pack(side="left", padx=(8, 0))
        self.restart_button = ttk.Button(bar, text="Restart", style="Restart.TButton", command=self._confirm_restart)
        self.restart_button.pack(side="left", padx=(8, 0))
        self.open_button = ttk.Button(bar, text="Open Mining360", style="Secondary.TButton", command=self._open_application)
        self.open_button.pack(side="left", padx=(16, 0))
        ttk.Button(bar, text="Actualiser", style="Secondary.TButton", command=self.refresh_all).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="Diagnostics", style="Secondary.TButton", command=self._run_diagnostics).pack(side="right")
        ttk.Button(bar, text="Journaux", style="Secondary.TButton", command=self._open_logs).pack(side="right", padx=(0, 8))

    def _build_navigation(self, parent) -> None:
        nav = tk.Frame(parent, bg=COLORS["surface"], height=40)
        nav.grid(row=2, column=0, sticky="ew")
        nav.pack_propagate(False)
        self.nav_buttons = {}
        for name in ("Overview", "Services", "Data & Integrations", "Jobs", "Deployment", "Logs & History"):
            button = tk.Button(
                nav, text=name, command=lambda value=name: self._change_view(value),
                bg=COLORS["surface"], fg=COLORS["text"] if name == "Overview" else COLORS["muted"],
                activebackground=COLORS["surface_hover"], activeforeground=COLORS["text"],
                relief="flat", bd=0, padx=15, font=("Segoe UI Semibold", 9), cursor="hand2",
            )
            button.pack(side="left", fill="y")
            self.nav_buttons[name] = button

    def _build_operation_panel(self, parent) -> None:
        self.operation_panel = tk.Frame(
            parent, bg=COLORS["surface_high"], highlightthickness=1, highlightbackground=COLORS["blue"]
        )
        self.operation_title = tk.Label(
            self.operation_panel, text="Operation", bg=COLORS["surface_high"], fg=COLORS["text"],
            font=("Segoe UI Semibold", 10),
        )
        self.operation_title.pack(side="left", padx=(14, 12), pady=10)
        self.operation_detail = tk.Label(
            self.operation_panel, text="", bg=COLORS["surface_high"], fg=COLORS["muted"], font=("Segoe UI", 9)
        )
        self.operation_detail.pack(side="left", padx=(0, 12))
        self.operation_progress = ttk.Progressbar(self.operation_panel, mode="determinate", length=240)
        self.operation_progress.pack(side="right", padx=14, pady=12)

    def _build_workspace(self, parent) -> None:
        self.workspace = tk.PanedWindow(
            parent, orient="horizontal", bg=COLORS["background"], sashwidth=6,
            sashrelief="flat", borderwidth=0, showhandle=False,
        )
        self.workspace.grid(row=4, column=0, sticky="nsew", pady=(12, 0))
        overview = tk.Frame(self.workspace, bg=COLORS["background"])
        overview.columnconfigure(0, weight=1)
        overview.rowconfigure(1, weight=1)
        title_row = tk.Frame(overview, bg=COLORS["background"])
        title_row.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.workspace_title = tk.Label(
            title_row, text="Platform Services", bg=COLORS["background"], fg=COLORS["text"],
            font=("Segoe UI Semibold", 13),
        )
        self.workspace_title.pack(side="left")
        self.workspace_hint = tk.Label(
            title_row, text="Select a service for health evidence and safe actions.",
            bg=COLORS["background"], fg=COLORS["muted"], font=("Segoe UI", 8),
        )
        self.workspace_hint.pack(side="right")
        service_viewport = tk.Frame(overview, bg=COLORS["background"])
        service_viewport.grid(row=1, column=0, sticky="nsew")
        service_viewport.columnconfigure(0, weight=1)
        service_viewport.rowconfigure(0, weight=1)
        self.service_canvas = tk.Canvas(
            service_viewport, bg=COLORS["background"], highlightthickness=0, borderwidth=0
        )
        self.service_canvas.grid(row=0, column=0, sticky="nsew")
        service_scrollbar = ttk.Scrollbar(service_viewport, orient="vertical", command=self.service_canvas.yview)
        service_scrollbar.grid(row=0, column=1, sticky="ns")
        self.service_canvas.configure(yscrollcommand=service_scrollbar.set)
        self.service_grid = tk.Frame(self.service_canvas, bg=COLORS["background"])
        self.service_window = self.service_canvas.create_window((0, 0), window=self.service_grid, anchor="nw")
        self.service_grid.bind(
            "<Configure>",
            lambda _event: self.service_canvas.configure(scrollregion=self.service_canvas.bbox("all")),
        )
        self.service_canvas.bind(
            "<Configure>",
            lambda event: self.service_canvas.itemconfigure(self.service_window, width=event.width),
        )
        self.card_columns = 2
        for column in range(self.card_columns):
            self.service_grid.columnconfigure(column, weight=1, uniform="services")
        self._render_cards()

        details = tk.Frame(
            self.workspace, bg=COLORS["surface"], width=310,
            highlightthickness=1, highlightbackground=COLORS["border"],
        )
        details.pack_propagate(False)
        self.detail_category = tk.Label(
            details, text="RUNTIME", bg=COLORS["surface"], fg=COLORS["yellow"], font=("Segoe UI Semibold", 8)
        )
        self.detail_category.pack(anchor="w", padx=18, pady=(18, 3))
        self.detail_title = tk.Label(
            details, text="Django / Waitress", bg=COLORS["surface"], fg=COLORS["text"],
            font=("Segoe UI Semibold", 16), anchor="w",
        )
        self.detail_title.pack(fill="x", padx=18)
        self.detail_status = tk.Label(
            details, text="Checking", bg=COLORS["surface"], fg=COLORS["gray"],
            font=("Segoe UI Semibold", 10), anchor="w",
        )
        self.detail_status.pack(fill="x", padx=18, pady=(8, 0))
        self.detail_text = tk.Text(
            details, bg=COLORS["surface"], fg=COLORS["muted"], insertbackground=COLORS["text"],
            relief="flat", bd=0, wrap="word", font=("Segoe UI", 9), padx=0, pady=12, height=11,
        )
        self.detail_text.pack(fill="both", expand=True, padx=18)
        self.detail_text.configure(state="disabled")
        ttk.Button(details, text="Open Related Logs", style="Secondary.TButton", command=self._open_logs).pack(
            anchor="w", padx=18, pady=(0, 16)
        )
        self.workspace.add(overview, minsize=520, stretch="always")
        self.workspace.add(details, minsize=280, stretch="never")

        activity = tk.Frame(overview, bg=COLORS["surface"], highlightthickness=1, highlightbackground=COLORS["border"])
        activity.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        header = tk.Frame(activity, bg=COLORS["surface"])
        header.pack(fill="x", padx=12, pady=(8, 4))
        tk.Label(header, text="LIVE ACTIVITY", bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI Semibold", 8)).pack(side="left")
        self.activity_text = tk.Text(
            activity, height=5, bg="#091222", fg="#B9C6D9", relief="flat", bd=0,
            font=("Cascadia Mono", 8), padx=10, pady=8, wrap="word", state="disabled",
        )
        self.activity_text.pack(fill="x", padx=12, pady=(0, 10))
        self._append_activity("INFO", "Control Center V2 ready.")

    def _build_footer(self) -> None:
        footer = tk.Frame(self, bg=COLORS["navy"], height=28)
        footer.pack(fill="x", side="bottom")
        self.footer_status = tk.Label(
            footer, text="Health checks initializing", bg=COLORS["navy"], fg=COLORS["muted"], font=("Segoe UI", 8)
        )
        self.footer_status.pack(side="left", padx=22)
        tk.Label(
            footer, text="Control Center V2 · Safe Operations", bg=COLORS["navy"], fg=COLORS["muted"], font=("Segoe UI", 8)
        ).pack(side="right", padx=22)

    def _render_cards(self) -> None:
        for widget in self.service_grid.winfo_children():
            widget.destroy()
        self.cards.clear()
        definitions = list(self.registry.services())
        if self.current_view == "Overview":
            primary = {"process", "django", "https", "database", "codex_worker", "active_directory", "powerbi"}
            definitions = [item for item in definitions if item.code in primary]
        elif self.current_view == "Services":
            definitions = [item for item in definitions if item.category in {"Runtime", "Identity & Security", "AI & Workers"}]
        elif self.current_view == "Data & Integrations":
            definitions = [item for item in definitions if item.category in {"Data & Integrations", "Identity & Security"}]
        elif self.current_view == "Jobs":
            definitions = [item for item in definitions if item.category == "AI & Workers"]
        elif self.current_view == "Deployment":
            definitions = []
        for index, definition in enumerate(definitions):
            card = ServiceCard(self.service_grid, definition, self._select_service)
            column = index % self.card_columns
            card.grid(
                row=index // self.card_columns,
                column=column,
                sticky="nsew",
                padx=(0, 8) if column < self.card_columns - 1 else (0, 0),
                pady=(0, 8),
            )
            self.cards[definition.code] = card
            if definition.code in self.results:
                card.set_result(self.results[definition.code])
        if not definitions:
            message = "Deployment controls are available through the governed web deployment workflow."
            tk.Label(
                self.service_grid, text=message, bg=COLORS["surface"], fg=COLORS["muted"],
                font=("Segoe UI", 10), padx=24, pady=30,
            ).grid(row=0, column=0, columnspan=self.card_columns, sticky="ew")

    def _change_view(self, view: str) -> None:
        self.current_view = view
        for name, button in self.nav_buttons.items():
            button.configure(fg=COLORS["text"] if name == view else COLORS["muted"])
        if view == "Logs & History":
            self._open_logs()
            return
        self.workspace_title.configure(text=view)
        self._render_cards()

    def _select_service(self, code: str) -> None:
        self.selected_service = code
        self._update_detail()

    def _update_detail(self) -> None:
        definition = self.definitions.get(self.selected_service)
        if not definition:
            return
        result = self.results.get(definition.code)
        self.detail_category.configure(text=definition.category.upper())
        self.detail_title.configure(text=definition.name)
        if result:
            status_text, color = STATUS_META.get(result.status, STATUS_META["unknown"])
            checked = datetime.fromtimestamp(result.checked_at).strftime("%d %b %Y · %H:%M:%S")
            body = (
                f"Health summary\n{_friendly_detail(result)}\n\n"
                f"Health evidence\nLast checked: {checked}\n"
                f"Criticality: {definition.criticality.title()}\n"
                f"Required: {'Yes' if definition.required else 'No'}\n"
                f"Expected port: {definition.port or 'Not applicable'}\n\n"
                f"Dependencies\n{', '.join(definition.dependencies) if definition.dependencies else 'None'}"
            )
        else:
            status_text, color = STATUS_META["unknown"]
            body = "This service has not been evaluated yet.\n\nRun Refresh to collect health evidence."
        self.detail_status.configure(text=status_text, fg=color)
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")
        self.detail_text.insert("1.0", body)
        self.detail_text.configure(state="disabled")

    def refresh_all(self) -> None:
        self._submit_check("fast", self.controller.check_runtime_services)
        self._submit_check("medium", self.controller.check_application_services)
        self._submit_check("slow", self.controller.check_external_services)
        self._submit_check("extended", self.extended_health.check)
        self._append_activity("INFO", "Manual health refresh requested.")

    def _refresh_fast(self) -> None:
        if self.closed:
            return
        self._submit_check("fast", self.controller.check_runtime_services)
        self.after(self.FAST_REFRESH_MS, self._refresh_fast)

    def _refresh_medium(self) -> None:
        if self.closed:
            return
        self._submit_check("medium", self.controller.check_application_services)
        self.after(self.MEDIUM_REFRESH_MS, self._refresh_medium)

    def _refresh_slow(self) -> None:
        if self.closed:
            return
        self._submit_check("slow", self.controller.check_external_services)
        self._submit_check("extended", self.extended_health.check)
        self.after(self.SLOW_REFRESH_MS, self._refresh_slow)

    def _submit_check(self, cadence: str, function) -> None:
        if cadence in self.checks_running or self.lifecycle.operation_running:
            return
        self.checks_running.add(cadence)
        future = self.executor.submit(function)
        future.add_done_callback(lambda completed: self._queue_future("health", cadence, completed))

    def _run_lifecycle(self, action: str) -> None:
        if self.lifecycle.operation_running:
            return
        method = getattr(self.lifecycle, action)
        self.operation_panel.grid(row=3, column=0, sticky="ew", pady=(0, 2))
        self.operation_title.configure(text=f"{action.title()}ing Mining 360")
        self.operation_detail.configure(text="Preparing controlled operation...")
        self.operation_progress.configure(value=0, maximum=100)
        self._append_activity("LIFECYCLE", f"{action.title()} requested.")

        def progress(step: OperationStep) -> None:
            self.events.put(("progress", step))

        future = self.executor.submit(method, progress)
        future.add_done_callback(lambda completed: self._queue_future("operation", action, completed))
        self._update_action_states(force_disabled=True)

    def _confirm_restart(self) -> None:
        environment = self.registry.environment
        if environment.casefold() == "production":
            accepted = self._production_confirmation()
        else:
            accepted = messagebox.askokcancel(
                "Restart Mining 360",
                f"Environment: {environment}\n\nManaged components:\n"
                "- Django / Waitress\n- Codex Worker\n- HTTPS Gateway\n\n"
                "The managed services will be stopped and started in a controlled sequence.",
                parent=self,
            )
        if accepted:
            self._run_lifecycle("restart")

    def _production_confirmation(self) -> bool:
        dialog = tk.Toplevel(self)
        dialog.title("Production confirmation")
        dialog.configure(bg=COLORS["surface"])
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)
        tk.Label(
            dialog, text="Restart Production", bg=COLORS["surface"], fg=COLORS["red"],
            font=("Segoe UI Semibold", 15),
        ).pack(anchor="w", padx=22, pady=(20, 8))
        tk.Label(
            dialog, text="Type PRODUCTION to confirm the controlled restart.", bg=COLORS["surface"],
            fg=COLORS["text"], font=("Segoe UI", 10),
        ).pack(anchor="w", padx=22)
        entry = tk.Entry(dialog, width=34, bg=COLORS["surface_high"], fg=COLORS["text"], insertbackground=COLORS["text"])
        entry.pack(fill="x", padx=22, pady=14)
        accepted = {"value": False}
        buttons = tk.Frame(dialog, bg=COLORS["surface"])
        buttons.pack(fill="x", padx=22, pady=(0, 20))
        confirm = ttk.Button(buttons, text="Restart Production", style="Danger.TButton", state="disabled")
        confirm.pack(side="right")
        ttk.Button(buttons, text="Cancel", style="Secondary.TButton", command=dialog.destroy).pack(side="right", padx=8)

        def validate(_event=None) -> None:
            confirm.configure(state="normal" if entry.get().strip() == "PRODUCTION" else "disabled")

        def finish() -> None:
            accepted["value"] = True
            dialog.destroy()

        entry.bind("<KeyRelease>", validate)
        confirm.configure(command=finish)
        entry.focus_set()
        self.wait_window(dialog)
        return accepted["value"]

    def _run_diagnostics(self) -> None:
        self._append_activity("INFO", "System diagnostics started.")

        def diagnose():
            try:
                os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Mining360IA.settings")
                import django
                django.setup()
                from deployment.services.system_doctor import DeploymentSystemDoctorService
                return DeploymentSystemDoctorService().run()
            except Exception as exc:
                return {"status": "Unavailable", "checks": [], "error": self.controller.redact(str(exc))}

        future = self.executor.submit(diagnose)
        future.add_done_callback(lambda completed: self._queue_future("diagnostics", "diagnostics", completed))

    def _show_diagnostics(self, payload: dict) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Mining 360 Diagnostics")
        dialog.geometry("920x620")
        dialog.configure(bg=COLORS["background"])
        tk.Label(
            dialog, text=f"System Doctor · {payload.get('status', 'Unknown')}",
            bg=COLORS["navy"], fg=COLORS["text"], font=("Segoe UI Semibold", 16), padx=20, pady=16,
        ).pack(fill="x")
        text_widget = tk.Text(
            dialog, bg=COLORS["surface"], fg=COLORS["text"], insertbackground=COLORS["text"],
            relief="flat", font=("Cascadia Mono", 9), padx=16, pady=14, wrap="word",
        )
        text_widget.pack(fill="both", expand=True, padx=18, pady=18)
        if payload.get("error"):
            text_widget.insert("end", payload["error"])
        for item in payload.get("checks", []):
            text_widget.insert(
                "end",
                f"[{item.get('status', 'Unknown')}] {item.get('name', '')}\n"
                f"{item.get('value', '')}\n{item.get('recommendation', '')}\n\n",
            )
        text_widget.configure(state="disabled")

    def _queue_future(self, event_type: str, context: str, completed) -> None:
        try:
            value = completed.result()
        except Exception as exc:
            value = exc
        self.events.put((event_type, (context, value)))

    def _drain_events(self) -> None:
        try:
            while True:
                event_type, payload = self.events.get_nowait()
                if event_type == "health":
                    cadence, value = payload
                    self.checks_running.discard(cadence)
                    if isinstance(value, Exception):
                        self._append_activity("ERROR", f"{cadence.title()} health check failed: {value}")
                    else:
                        self._apply_results(value)
                elif event_type == "progress":
                    self._apply_progress(payload)
                elif event_type == "operation":
                    action, value = payload
                    self._complete_operation(action, value)
                elif event_type == "diagnostics":
                    _context, value = payload
                    if isinstance(value, Exception):
                        self._append_activity("ERROR", f"Diagnostics failed: {value}")
                    else:
                        self._show_diagnostics(value)
        except queue.Empty:
            pass
        if not self.closed:
            self.after(100, self._drain_events)

    def _apply_results(self, results: dict[str, ServiceResult]) -> None:
        self.results.update(results)
        for code, result in results.items():
            if code in self.cards:
                self.cards[code].set_result(result)
        self._update_summary()
        self._update_detail()
        self._update_action_states()

    def _update_summary(self) -> None:
        required = [item for item in self.registry.services() if item.required]
        required_results = [self.results.get(item.code) for item in required]
        operational = sum(item is not None and item.status == "online" for item in required_results)
        degraded = sum(item is not None and item.status == "degraded" for item in self.results.values())
        unavailable_required = any(item is not None and item.status == "offline" for item in required_results)
        optional_failure = any(
            result.status in {"offline", "degraded"}
            for code, result in self.results.items()
            if code in self.definitions and not self.definitions[code].required
        )
        if self.lifecycle.operation_running:
            label, color = "Updating", COLORS["blue"]
        elif (self.results.get("django") and self.results["django"].status == "online"
              and self.results.get("https") and self.results["https"].status != "online"):
            label, color = "Local OK / HTTPS not configured", COLORS["amber"]
        elif unavailable_required:
            label, color = "Unavailable", COLORS["red"]
        elif operational == len(required) and not optional_failure:
            label, color = "Operational", COLORS["green"]
        elif self.results:
            label, color = "Degraded", COLORS["amber"]
        else:
            label, color = "Unknown", COLORS["gray"]
        incidents = sum(result.status == "offline" for result in self.results.values()) if self.results else None
        self.summary_values["global"].configure(text=label, fg=color)
        self.summary_values["operational"].configure(text=f"{operational} / {len(required)}")
        self.summary_values["degraded"].configure(text=str(degraded))
        self.summary_values["incidents"].configure(text=str(incidents) if incidents is not None else "Not Evaluated")
        self.summary_values["checked"].configure(text=time.strftime("%H:%M:%S"))
        self.footer_status.configure(text=f"{label} · {operational}/{len(required)} required services operational")

        if self.results.get("django") and self.results["django"].status == "online" and self.results.get("https") and self.results["https"].status != "online":
            self.footer_status.configure(text="Local application operational, HTTPS not configured")

    def _apply_progress(self, step: OperationStep) -> None:
        value = int(step.index / max(step.total, 1) * 100)
        self.operation_title.configure(text=f"Mining 360 · {step.label}")
        self.operation_detail.configure(text=f"Step {step.index} of {step.total}")
        self.operation_progress.configure(value=value)
        self._append_activity("LIFECYCLE", step.label)

    def _complete_operation(self, action: str, value: object) -> None:
        if isinstance(value, (Exception, OperationInProgressError)):
            self.operation_title.configure(text="Operation failed")
            self.operation_detail.configure(text=self.controller.redact(str(value)))
            self._append_activity("ERROR", f"{action.title()} failed: {value}")
        else:
            result = value
            assert isinstance(result, OperationResult)
            self.operation_result = result
            color = COLORS["green"] if result.status == OperationStatus.COMPLETED else (
                COLORS["amber"] if result.status == OperationStatus.COMPLETED_WITH_WARNINGS else COLORS["red"]
            )
            self.operation_panel.configure(highlightbackground=color)
            self.operation_title.configure(text=result.message)
            duration = result.completed_at - result.started_at
            detail = f"{duration:.1f}s · Operation {result.operation_id[:8]}"
            if result.warnings:
                detail += f" · {len(result.warnings)} warning(s)"
            self.operation_detail.configure(text=detail)
            self.operation_progress.configure(value=100)
            level = "INFO" if result.status == OperationStatus.COMPLETED else "WARNING"
            self._append_activity(level, f"{result.message} ({result.operation_id})")
        self._update_action_states()
        self.after(400, self.refresh_all)

    def _update_action_states(self, force_disabled: bool = False) -> None:
        if force_disabled or self.lifecycle.operation_running or not self.registry.lifecycle_supported:
            for button in (self.start_button, self.stop_button, self.restart_button, self.open_button):
                button.configure(state="disabled")
            return
        process_result = self.results.get("process")
        codex_result = self.results.get("codex_worker")
        https_result = self.results.get("https")
        ownership_unverified = any(
            "ownership is unverified" in (result.detail or "").casefold()
            for result in (process_result, codex_result)
            if result is not None
        )
        running = bool(
            (process_result and process_result.status in {"online", "degraded"})
            or (codex_result and codex_result.status in {"online", "degraded"})
            or (https_result and https_result.status == "online")
        )
        required_online = all(
            self.results.get(item.code) and self.results[item.code].status == "online"
            for item in self.registry.services() if item.required
        )
        self.start_button.configure(state="disabled" if running or required_online or ownership_unverified else "normal")
        self.stop_button.configure(state="normal" if running and not ownership_unverified else "disabled")
        self.restart_button.configure(state="normal" if running and not ownership_unverified else "disabled")
        https_ready = self.results.get("https") and self.results["https"].status == "online"
        local_ready = self.results.get("django") and self.results["django"].status == "online"
        self.open_button.configure(state="normal" if https_ready or local_ready else "disabled")

    def _open_application(self) -> None:
        result = self.results.get("https")
        if not result or result.status != "online":
            result = self.results.get("django")
        if not result or result.status != "online" or time.time() - result.checked_at > 35:
            messagebox.showwarning(
                "Mining 360 is not ready",
                "The application is not ready or its health check has expired.",
                parent=self,
            )
            return
        target = self.controller.public_url if self.results.get("https") and self.results["https"].status == "online" else self.controller.upstream_url
        webbrowser.open(target, new=0)
        self.event_store.append({"type": "open_application", "url": target})
        self._append_activity("INFO", f"Opened {target}")

    def _open_logs(self) -> None:
        try:
            self.controller.open_logs_directory()
        except OSError as exc:
            self._append_activity("ERROR", f"Unable to open logs: {exc}")

    def _append_activity(self, level: str, message: str) -> None:
        if not hasattr(self, "activity_text"):
            return
        safe = self.controller.redact(message)
        self.activity_text.configure(state="normal")
        self.activity_text.insert("end", f"{time.strftime('%H:%M:%S')}  {level:<10} {safe}\n")
        self.activity_text.see("end")
        self.activity_text.configure(state="disabled")

    def _update_clock(self) -> None:
        if self.closed:
            return
        self.clock_label.configure(text=time.strftime("%d %b %Y · %H:%M:%S"))
        self.after(1000, self._update_clock)

    def _on_close(self) -> None:
        self.closed = True
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.destroy()


def _friendly_detail(result: ServiceResult) -> str:
    detail = result.detail or "No health detail available."
    folded = detail.casefold()
    if "winerror 10061" in folded or "actively refused" in folded or "connection refused" in folded:
        return "Connection refused. The service is not listening on the expected address."
    if "timed out" in folded or "timeout" in folded:
        return "The health check timed out. Open Diagnostics for technical evidence."
    return detail


def _windows_authorization_label() -> str:
    try:
        return "Windows Administrator" if ctypes.windll.shell32.IsUserAnAdmin() else "Standard Windows User"
    except (AttributeError, OSError):
        return "Windows authorization unknown"


def main() -> None:
    Mining360ControlCenterV2().mainloop()


if __name__ == "__main__":
    main()
