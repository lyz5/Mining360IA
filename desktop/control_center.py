from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from tkinter import font as tkfont
from tkinter import ttk

from desktop.control_core import Mining360Controller, ServiceResult


COLORS = {
    "window": "#F2F4F7",
    "panel": "#FFFFFF",
    "navy": "#121A31",
    "navy_soft": "#27314B",
    "text": "#182033",
    "muted": "#667085",
    "border": "#E1E5EA",
    "yellow": "#FFD400",
    "yellow_hover": "#EEC600",
    "green": "#12A66A",
    "red": "#D64545",
    "gray": "#98A2B3",
    "blue": "#3478F6",
}


class StatusCard(tk.Frame):
    def __init__(self, master, code: str, label: str) -> None:
        super().__init__(master, bg=COLORS["panel"], highlightthickness=1, highlightbackground=COLORS["border"])
        self.code = code
        self.columnconfigure(1, weight=1)
        self.indicator = tk.Canvas(self, width=26, height=26, bg=COLORS["panel"], highlightthickness=0)
        self.indicator.grid(row=0, column=0, rowspan=2, padx=(16, 12), pady=17, sticky="n")
        self.dot = self.indicator.create_oval(5, 5, 21, 21, fill=COLORS["gray"], outline="")
        self.title = tk.Label(
            self,
            text=label,
            bg=COLORS["panel"],
            fg=COLORS["text"],
            font=("Segoe UI Semibold", 11),
            anchor="w",
        )
        self.title.grid(row=0, column=1, padx=(0, 14), pady=(14, 1), sticky="ew")
        self.detail = tk.Label(
            self,
            text="En attente du statut",
            bg=COLORS["panel"],
            fg=COLORS["muted"],
            font=("Segoe UI", 9),
            anchor="w",
            justify="left",
            wraplength=310,
        )
        self.detail.grid(row=1, column=1, padx=(0, 14), pady=(0, 13), sticky="new")
        self.state = "unknown"

    def set_result(self, result: ServiceResult) -> None:
        self.state = result.status
        color = {
            "online": COLORS["green"],
            "offline": COLORS["red"],
            "checking": COLORS["blue"],
            "unknown": COLORS["gray"],
        }.get(result.status, COLORS["gray"])
        self.indicator.itemconfigure(self.dot, fill=color)
        self.detail.configure(text=result.detail or result.status.title())


class ControlCenter(tk.Tk):
    LOCAL_REFRESH_MS = 4000
    EXTERNAL_REFRESH_MS = 30000

    def __init__(self) -> None:
        super().__init__()
        self.title("Mining 360 Control Center")
        self.geometry("960x720")
        self.minsize(760, 620)
        self.configure(bg=COLORS["window"])
        self.controller = Mining360Controller()
        self.executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="mining360-control")
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.cards: dict[str, StatusCard] = {}
        self.results: dict[str, ServiceResult] = {}
        self.local_check_running = False
        self.external_check_running = False
        self.action_running = False
        self._closed = False
        self._configure_styles()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._drain_events)
        self.after(250, self._poll_local)
        self.after(500, self._poll_external)

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "Primary.TButton",
            background=COLORS["yellow"],
            foreground=COLORS["navy"],
            bordercolor=COLORS["yellow"],
            padding=(18, 10),
            font=("Segoe UI Semibold", 10),
        )
        style.map("Primary.TButton", background=[("active", COLORS["yellow_hover"]), ("disabled", "#E5E7EB")])
        style.configure(
            "Secondary.TButton",
            background=COLORS["panel"],
            foreground=COLORS["text"],
            bordercolor=COLORS["border"],
            padding=(16, 10),
            font=("Segoe UI Semibold", 10),
        )
        style.map("Secondary.TButton", background=[("active", "#F8FAFC")])
        style.configure(
            "Danger.TButton",
            background="#FFF4F3",
            foreground="#B42318",
            bordercolor="#FDA29B",
            padding=(18, 10),
            font=("Segoe UI Semibold", 10),
        )
        style.map("Danger.TButton", background=[("active", "#FEE4E2"), ("disabled", "#F5F5F5")])

    def _build_ui(self) -> None:
        header = tk.Frame(self, bg=COLORS["navy"], height=112)
        header.pack(fill="x")
        header.pack_propagate(False)
        brand = tk.Frame(header, bg=COLORS["navy"])
        brand.pack(side="left", fill="y", padx=28, pady=20)
        mark = tk.Label(
            brand,
            text="M360",
            bg=COLORS["yellow"],
            fg=COLORS["navy"],
            font=("Segoe UI Black", 11),
            padx=9,
            pady=7,
        )
        mark.pack(side="left", padx=(0, 14))
        title_box = tk.Frame(brand, bg=COLORS["navy"])
        title_box.pack(side="left")
        tk.Label(
            title_box,
            text="Mining 360 Control Center",
            bg=COLORS["navy"],
            fg="white",
            font=("Segoe UI Semibold", 18),
        ).pack(anchor="w")
        tk.Label(
            title_box,
            text="Pilotage des services et de la connectivite",
            bg=COLORS["navy"],
            fg="#AEB8CC",
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(2, 0))
        self.overall = tk.Label(
            header,
            text="Verification",
            bg=COLORS["navy"],
            fg="#AEB8CC",
            font=("Segoe UI Semibold", 10),
        )
        self.overall.pack(side="right", padx=28)

        content = tk.Frame(self, bg=COLORS["window"])
        content.pack(fill="both", expand=True, padx=26, pady=20)
        content.columnconfigure(0, weight=1)
        content.rowconfigure(2, weight=1)

        action_bar = tk.Frame(content, bg=COLORS["window"])
        action_bar.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        self.start_button = ttk.Button(action_bar, text="Demarrer", style="Primary.TButton", command=self.start_application)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(action_bar, text="Arreter", style="Danger.TButton", command=self.stop_application)
        self.stop_button.pack(side="left", padx=9)
        ttk.Button(action_bar, text="Ouvrir", style="Secondary.TButton", command=self.open_application).pack(side="left")
        ttk.Button(action_bar, text="Actualiser", style="Secondary.TButton", command=self.refresh_all).pack(side="left", padx=9)
        service_grid = tk.Frame(content, bg=COLORS["window"])
        service_grid.grid(row=1, column=0, sticky="ew")
        for column in range(2):
            service_grid.columnconfigure(column, weight=1, uniform="services")
        for index, (code, label) in enumerate(self.controller.SERVICE_LABELS.items()):
            card = StatusCard(service_grid, code, label)
            card.grid(row=index // 2, column=index % 2, padx=(0 if index % 2 == 0 else 7, 0), pady=(0, 7), sticky="nsew")
            self.cards[code] = card

        log_panel = tk.Frame(content, bg=COLORS["panel"], highlightthickness=1, highlightbackground=COLORS["border"])
        log_panel.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        log_panel.columnconfigure(0, weight=1)
        log_panel.rowconfigure(1, weight=1)
        log_header = tk.Frame(log_panel, bg=COLORS["panel"])
        log_header.grid(row=0, column=0, sticky="ew", padx=15, pady=(12, 7))
        tk.Label(
            log_header,
            text="Activite",
            bg=COLORS["panel"],
            fg=COLORS["text"],
            font=("Segoe UI Semibold", 11),
        ).pack(side="left")
        ttk.Button(log_header, text="Ouvrir les journaux", style="Secondary.TButton", command=self.open_logs).pack(side="right")
        self.log_text = tk.Text(
            log_panel,
            bg="#F8FAFC",
            fg="#344054",
            borderwidth=0,
            highlightthickness=0,
            font=("Cascadia Mono", 9),
            padx=12,
            pady=10,
            state="disabled",
            wrap="word",
        )
        self.log_text.grid(row=1, column=0, sticky="nsew", padx=15, pady=(0, 14))
        self._append_log("Centre de controle pret.")

    def start_application(self) -> None:
        if self.action_running:
            return
        self.action_running = True
        self._set_action_buttons(False)
        self._append_log("Demarrage de Mining 360...")
        self._submit("action", self.controller.start, "start")

    def stop_application(self) -> None:
        if self.action_running:
            return
        self.action_running = True
        self._set_action_buttons(False)
        self._append_log("Arret de Mining 360...")
        self._submit("action", self.controller.stop, "stop")

    def open_application(self) -> None:
        webbrowser.open(self.controller.public_url)
        self._append_log(f"Opened {self.controller.public_url}")

    def open_logs(self) -> None:
        try:
            self.controller.open_logs_directory()
        except OSError as exc:
            self._append_log(f"Unable to open logs: {exc}")

    def refresh_all(self) -> None:
        self._request_local_refresh()
        self._request_external_refresh()

    def _request_local_refresh(self) -> None:
        if not self.local_check_running:
            self.local_check_running = True
            self._submit("local", self.controller.check_local_services)

    def _request_external_refresh(self) -> None:
        if not self.external_check_running:
            self.external_check_running = True
            self._submit("external", self.controller.check_external_services)

    def _poll_local(self) -> None:
        if self._closed:
            return
        self._request_local_refresh()
        self.after(self.LOCAL_REFRESH_MS, self._poll_local)

    def _poll_external(self) -> None:
        if self._closed:
            return
        self._request_external_refresh()
        self.after(self.EXTERNAL_REFRESH_MS, self._poll_external)

    def _submit(self, event_type: str, function, *args) -> None:
        future = self.executor.submit(function)

        def complete(completed) -> None:
            try:
                value = completed.result()
            except Exception as exc:
                value = exc
            self.events.put((event_type, (value, *args)))

        future.add_done_callback(complete)

    def _drain_events(self) -> None:
        try:
            while True:
                event_type, payload = self.events.get_nowait()
                if event_type in {"local", "external"}:
                    value = payload[0]
                    if event_type == "local":
                        self.local_check_running = False
                    else:
                        self.external_check_running = False
                    if isinstance(value, Exception):
                        self._append_log(f"Status check failed: {value}")
                    else:
                        self._apply_results(value)
                elif event_type == "action":
                    value, action = payload
                    self.action_running = False
                    self._set_action_buttons(True)
                    if isinstance(value, Exception):
                        self._append_log(f"{action.title()} failed: {value}")
                    else:
                        success, message = value
                        self._append_log(message)
                        if not success:
                            self.bell()
                    self.after(300, self._request_local_refresh)
        except queue.Empty:
            pass
        self.after(120, self._drain_events)

    def _apply_results(self, results: dict[str, ServiceResult]) -> None:
        self.results.update(results)
        for code, result in results.items():
            if code in self.cards:
                self.cards[code].set_result(result)
        statuses = [result.status for result in self.results.values()]
        if statuses and all(status == "online" for status in statuses) and len(statuses) == len(self.cards):
            self.overall.configure(text="Operationnel", fg=COLORS["green"])
        elif any(status == "offline" for status in statuses):
            self.overall.configure(text="Attention", fg=COLORS["red"])
        else:
            self.overall.configure(text="Verification", fg=COLORS["muted"])

    def _set_action_buttons(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.start_button.configure(state=state)
        self.stop_button.configure(state=state)

    def _append_log(self, message: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        safe_message = self.controller.redact(message)
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{timestamp}  {safe_message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _on_close(self) -> None:
        self._closed = True
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.destroy()


def main() -> None:
    app = ControlCenter()
    default_font = tkfont.nametofont("TkDefaultFont")
    default_font.configure(family="Segoe UI", size=9)
    app.mainloop()


if __name__ == "__main__":
    main()
