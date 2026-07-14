import json
import tkinter as tk
from tkinter import messagebox, ttk
import re
import subprocess
import pygetwindow as gw
import pyautogui
import platform
from datetime import datetime
from pathlib import Path
from pynput import mouse

if platform.system() == "Windows":
    import win32gui

POLL_MS    = 50
LOG_MAX    = 30_000
LOG_HEADROOM = 1_000  # rewrite is triggered once count reaches LOG_MAX + LOG_HEADROOM
LOG_PATH    = Path(__file__).parent / "clip_log.txt"
CONFIG_PATH = Path(__file__).parent / "config.json"
VIEWER_LIMIT = 500


# ── ClipLog ───────────────────────────────────────────────────────────────────

class ClipLog:
    """Append-only rolling log capped at LOG_MAX lines."""

    def __init__(self, path: Path):
        self._path = path
        if path.exists():
            with path.open(encoding="utf-8") as f:
                self._count = sum(1 for _ in f)
        else:
            self._count = 0

    def write(self, text: str, action: str, reason: str) -> None:
        ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        safe = text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
        line = f"{ts} | {action:<11} | {reason:<15} | {safe}\n"
        with self._path.open("a", encoding="utf-8") as f:
            f.write(line)
        self._count += 1
        if self._count >= LOG_MAX + LOG_HEADROOM:
            self._trim()

    def _trim(self) -> None:
        lines = self._path.read_text(encoding="utf-8").splitlines(keepends=True)
        lines = lines[-LOG_MAX:]
        self._path.write_text("".join(lines), encoding="utf-8")
        self._count = len(lines)


# ── LogViewer ─────────────────────────────────────────────────────────────────

class LogViewer(tk.Toplevel):
    def __init__(self, parent: tk.Tk, log_path: Path):
        super().__init__(parent)
        self._log_path = log_path
        self._all_entries: list[tuple[str, str, str, str]] = []
        self._auto_var = tk.BooleanVar(value=True)

        self.title("Clipboard Log")
        self.geometry("1000x520")
        self.minsize(600, 300)

        bar = tk.Frame(self, pady=4)
        bar.pack(fill=tk.X, padx=8)
        tk.Label(bar, text="Filter:").pack(side=tk.LEFT)
        self._filter_var = tk.StringVar()
        self._filter_var.trace_add("write", lambda *_: self._apply_filter())
        tk.Entry(bar, textvariable=self._filter_var, width=28).pack(side=tk.LEFT, padx=(4, 12))
        tk.Label(bar, text="Status:").pack(side=tk.LEFT)
        self._status_filter = tk.StringVar(value="All")
        self._status_filter.trace_add("write", lambda *_: self._apply_filter())
        ttk.Combobox(bar, textvariable=self._status_filter,
                     values=["All", "BLOCKED", "unblocked"],
                     state="readonly", width=10).pack(side=tk.LEFT, padx=(4, 12))
        tk.Button(bar, text="Refresh", command=self._load).pack(side=tk.LEFT, padx=(0, 6))
        tk.Checkbutton(bar, text="Auto-refresh (2 s)", variable=self._auto_var).pack(side=tk.LEFT, padx=(0, 12))
        tk.Button(bar, text="Open file", command=self._open_file).pack(side=tk.LEFT)

        frame = tk.Frame(self)
        frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 4))
        cols = ("ts", "action", "reason", "clip")
        self._tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="browse")
        self._tree.heading("ts",     text="Timestamp")
        self._tree.heading("action", text="Action")
        self._tree.heading("reason", text="Reason")
        self._tree.heading("clip",   text="Clipboard")
        self._tree.column("ts",     width=190, stretch=False)
        self._tree.column("action", width=80,  stretch=False)
        self._tree.column("reason", width=130, stretch=False)
        self._tree.column("clip",   width=540)
        vsb = ttk.Scrollbar(frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._tree.tag_configure("blocked",   background="#ffd6d6")
        self._tree.tag_configure("unblocked", background="#d6ffd6")

        self._bar_var = tk.StringVar()
        tk.Label(self, textvariable=self._bar_var, anchor="w",
                 font=("", 8)).pack(fill=tk.X, padx=8, pady=(0, 4))

        self._load()
        self._schedule_refresh()

    def _load(self) -> None:
        if not self._log_path.exists():
            self._bar_var.set("No log file yet.")
            return
        entries = []
        for line in self._log_path.read_text(encoding="utf-8").splitlines():
            parts = line.split(" | ", 3)
            if len(parts) == 4:
                entries.append(tuple(p.strip() for p in parts))
        self._all_entries = entries  # type: ignore[assignment]
        self._apply_filter()

    def _apply_filter(self) -> None:
        text_f   = self._filter_var.get().lower()
        status_f = self._status_filter.get()
        entries  = self._all_entries
        if status_f != "All":
            entries = [e for e in entries if e[1] == status_f]
        if text_f:
            entries = [e for e in entries if text_f in e[3].lower() or text_f in e[0]]
        shown = entries[-VIEWER_LIMIT:]
        self._tree.delete(*self._tree.get_children())
        for ts, action, reason, clip in shown:
            tag = "blocked" if action == "BLOCKED" else "unblocked"
            self._tree.insert("", "end", values=(ts, action, reason, clip), tags=(tag,))
        total = len(self._all_entries); filtered = len(entries); n = len(shown)
        msg = f"{n} rows shown"
        if filtered < total:
            msg += f"  (filter: {filtered} of {total})"
        else:
            msg += f"  of {total} total"
        if filtered > VIEWER_LIMIT:
            msg += f"  — last {VIEWER_LIMIT}"
        msg += f"    •  {self._log_path}"
        self._bar_var.set(msg)
        kids = self._tree.get_children()
        if kids:
            self._tree.see(kids[-1])

    def _open_file(self) -> None:
        if self._log_path.exists():
            subprocess.Popen(["notepad.exe", str(self._log_path)])
        else:
            messagebox.showinfo("Log", "No log file yet.")

    def _schedule_refresh(self) -> None:
        if not self.winfo_exists():
            return
        if self._auto_var.get():
            self._load()
        self.after(2000, self._schedule_refresh)


# ── PatternRow ────────────────────────────────────────────────────────────────

class PatternRow:
    def __init__(self, parent: tk.Frame, on_remove, on_change):
        self.enabled_var = tk.BooleanVar(value=True)
        self.desc_var    = tk.StringVar()
        self.pattern_var = tk.StringVar()
        self.compiled: re.Pattern | None = None

        self._frame = tk.Frame(parent)
        self._frame.pack(fill=tk.X, pady=1)

        tk.Checkbutton(self._frame, variable=self.enabled_var,
                       command=on_change).pack(side=tk.LEFT)
        tk.Entry(self._frame, textvariable=self.desc_var,
                 width=18).pack(side=tk.LEFT, padx=2)
        self._pat_entry = tk.Entry(self._frame, textvariable=self.pattern_var, width=28)
        self._pat_entry.pack(side=tk.LEFT, padx=2)
        tk.Button(self._frame, text="−", width=2,
                  command=lambda: on_remove(self)).pack(side=tk.LEFT, padx=2)

        self.desc_var.trace_add("write",    lambda *_: on_change())
        self.pattern_var.trace_add("write", lambda *_: on_change())
        self.enabled_var.trace_add("write", lambda *_: on_change())

    def mark_error(self, error: bool) -> None:
        self._pat_entry.config(bg="#ffd6d6" if error else "white")

    def destroy(self) -> None:
        self._frame.destroy()

    def to_dict(self) -> dict:
        return {"enabled": self.enabled_var.get(),
                "desc":    self.desc_var.get(),
                "pattern": self.pattern_var.get()}

    def load(self, d: dict) -> None:
        self.enabled_var.set(d.get("enabled", True))
        self.desc_var.set(d.get("desc", ""))
        self.pattern_var.set(d.get("pattern", ""))


# ── App ───────────────────────────────────────────────────────────────────────

class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self._hwnd: int | None = None
        self._is_active = False
        self._listener  = None
        self._rows: list[PatternRow] = []
        self._last_clip = ""
        self._log: ClipLog | None = None
        self._viewer: LogViewer | None = None
        self._save_after: str | None = None

        root.title("Regex Click Blocker")

        # ── window selection ──────────────────────────────────────────────
        r = tk.Frame(root, pady=4)
        r.pack(fill=tk.X, padx=10)
        tk.Label(r, text="Window:", width=8, anchor="w").pack(side=tk.LEFT)
        self._window_var = tk.StringVar()
        self._window_var.trace_add("write", lambda *_: self._schedule_save())
        self._window_combo = ttk.Combobox(r, textvariable=self._window_var,
                                          state="readonly", width=36)
        self._window_combo.pack(side=tk.LEFT, padx=(0, 4))
        tk.Button(r, text="↺", command=self._refresh_windows).pack(side=tk.LEFT)

        # ── pattern rows ──────────────────────────────────────────────────
        pf = tk.LabelFrame(root, text="Patterns", padx=6, pady=4)
        pf.pack(fill=tk.X, padx=10, pady=4)
        hdr = tk.Frame(pf)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="On",          width=3).pack(side=tk.LEFT)
        tk.Label(hdr, text="Description", width=18, anchor="w").pack(side=tk.LEFT, padx=2)
        tk.Label(hdr, text="Regex",       width=28, anchor="w").pack(side=tk.LEFT, padx=2)
        self._rows_frame = tk.Frame(pf)
        self._rows_frame.pack(fill=tk.X)
        tk.Button(pf, text="+ Add row", command=self._add_row).pack(anchor="e", pady=(4, 0))

        # ── options & buttons ─────────────────────────────────────────────
        self._invert_var = tk.BooleanVar()
        self._invert_var.trace_add("write", lambda *_: self._schedule_save())
        tk.Checkbutton(root, text="Block when regex not found",
                       variable=self._invert_var).pack(anchor="w", padx=18)

        btn = tk.Frame(root)
        btn.pack(pady=8)
        self._toggle_btn = tk.Button(btn, text="Start", width=12, command=self._on_toggle)
        self._toggle_btn.pack(side=tk.LEFT, padx=4)
        tk.Button(btn, text="Open Log", width=10, command=self._open_log).pack(side=tk.LEFT, padx=4)

        # ── clipboard display ─────────────────────────────────────────────
        r3 = tk.Frame(root, pady=4)
        r3.pack(fill=tk.X, padx=10)
        tk.Label(r3, text="Clipboard:", width=8, anchor="w").pack(side=tk.LEFT)
        self._clipboard_var = tk.StringVar()
        tk.Entry(r3, textvariable=self._clipboard_var,
                 state="readonly", width=40).pack(side=tk.LEFT)

        self._status_var = tk.StringVar(value="—")
        tk.Label(root, textvariable=self._status_var,
                 font=("", 9, "italic"), pady=4).pack()

        self._refresh_windows()
        self._load_config()
        if not self._rows:
            self._add_row()

    # ── pattern row management ────────────────────────────────────────────────

    def _add_row(self, data: dict | None = None) -> PatternRow:
        row = PatternRow(self._rows_frame, self._remove_row, self._schedule_save)
        if data:
            row.load(data)
        self._rows.append(row)
        self._schedule_save()
        return row

    def _remove_row(self, row: PatternRow) -> None:
        if len(self._rows) == 1:
            return
        row.destroy()
        self._rows.remove(row)
        self._schedule_save()

    # ── config persistence ────────────────────────────────────────────────────

    def _load_config(self) -> None:
        if not CONFIG_PATH.exists():
            return
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return
        self._window_var.set(cfg.get("window", ""))
        self._invert_var.set(cfg.get("invert", False))
        for d in cfg.get("patterns", []):
            self._add_row(d)

    def _schedule_save(self) -> None:
        if self._save_after:
            self.root.after_cancel(self._save_after)
        self._save_after = self.root.after(500, self._save_config)

    def _save_config(self) -> None:
        self._save_after = None
        cfg = {
            "window":   self._window_var.get(),
            "invert":   self._invert_var.get(),
            "patterns": [r.to_dict() for r in self._rows],
        }
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    # ── window list ───────────────────────────────────────────────────────────

    def _refresh_windows(self) -> None:
        own = self.root.title()
        titles = sorted({t for t in gw.getAllTitles() if t and t != own})
        self._window_combo["values"] = titles

    # ── start / stop ──────────────────────────────────────────────────────────

    def _on_toggle(self) -> None:
        if self._is_active:
            self._stop()
        else:
            self._start()

    def _start(self) -> None:
        title = self._window_var.get()
        if not title:
            messagebox.showinfo("Error", "Select a window first.")
            return

        errors: list[str] = []
        for row in self._rows:
            row.mark_error(False)
            row.compiled = None
            if row.enabled_var.get() and row.pattern_var.get():
                try:
                    row.compiled = re.compile(row.pattern_var.get())
                except re.error as exc:
                    row.mark_error(True)
                    label = row.desc_var.get() or row.pattern_var.get()
                    errors.append(f""{label}": {exc}")
        if errors:
            messagebox.showinfo("Invalid regex", "\n".join(errors))
            return
        if not any(r.compiled for r in self._rows):
            messagebox.showinfo("Error", "No enabled patterns with content.")
            return

        windows = gw.getWindowsWithTitle(title)
        if not windows:
            messagebox.showinfo("Error", "Window not found — refresh and try again.")
            return

        if platform.system() == "Windows":
            self._hwnd = windows[0]._hWnd

        self._log = ClipLog(LOG_PATH)
        self._last_clip = ""
        self._is_active = True
        self._toggle_btn.config(text="Stop")
        self._status_var.set("Starting...")
        self._start_listener()
        self.root.after(POLL_MS, self._tick)

    def _stop(self) -> None:
        self._is_active = False
        self._stop_listener()
        if platform.system() == "Windows" and self._hwnd:
            win32gui.EnableWindow(self._hwnd, True)
        self._hwnd = None
        self._log  = None
        self._toggle_btn.config(text="Start")
        self._status_var.set("Stopped")

    # ── mouse listener ────────────────────────────────────────────────────────

    def _start_listener(self) -> None:
        hwnd = self._hwnd

        def on_click(x, y, button, pressed):
            if not pressed or not self._is_active:
                return
            if platform.system() == "Windows" and hwnd and win32gui.IsWindowEnabled(hwnd):
                self.root.after(0, lambda: pyautogui.hotkey("ctrl", "c"))

        self._listener = mouse.Listener(on_click=on_click)
        self._listener.start()

    def _stop_listener(self) -> None:
        if self._listener:
            self._listener.stop()
            self._listener = None

    # ── polling tick ──────────────────────────────────────────────────────────

    def _matches_any(self, text: str) -> bool:
        return any(r.compiled and r.compiled.search(text) for r in self._rows)

    def _tick(self) -> None:
        if not self._is_active:
            return

        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            text = ""

        self._clipboard_var.set(text)

        if self._hwnd is not None:
            matched      = self._matches_any(text)
            should_block = matched if not self._invert_var.get() else not matched

            if platform.system() == "Windows":
                win32gui.EnableWindow(self._hwnd, not should_block)

            action = "BLOCKED" if should_block else "unblocked"
            reason = "regex found" if matched else "regex not found"
            self._status_var.set(f"{action} — {reason}")

            if text != self._last_clip and self._log is not None:
                self._log.write(text, action, reason)
                self._last_clip = text

        self.root.after(POLL_MS, self._tick)

    # ── log viewer ────────────────────────────────────────────────────────────

    def _open_log(self) -> None:
        if self._viewer and self._viewer.winfo_exists():
            self._viewer.lift()
            return
        self._viewer = LogViewer(self.root, LOG_PATH)


def main():
    root = tk.Tk()
    app = App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
