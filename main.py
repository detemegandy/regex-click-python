import tkinter as tk
from tkinter import messagebox, ttk
import re
import pygetwindow as gw
import pyautogui
import platform
from datetime import datetime
from pathlib import Path
from pynput import mouse

if platform.system() == "Windows":
    import win32gui

POLL_MS = 50       # clipboard re-evaluated this often; window state is always current before a click
LOG_MAX = 30_000   # rolling cap
LOG_TRIM = 1_000   # trim this many extra lines before rewriting to amortise the cost
LOG_PATH = Path(__file__).parent / "clip_log.txt"


class ClipLog:
    """Append-only rolling log capped at LOG_MAX lines."""

    def __init__(self, path: Path):
        self._path = path
        self._count = path.stat().st_size and sum(1 for _ in path.open(encoding="utf-8")) if path.exists() else 0

    def write(self, text: str, action: str, reason: str) -> None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        # Replace newlines in clipboard text so each log entry stays on one line.
        safe = text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
        line = f"{ts} | {action:<9} | {reason:<15} | {safe}\n"
        with self._path.open("a", encoding="utf-8") as f:
            f.write(line)
        self._count += 1
        if self._count > LOG_MAX + LOG_TRIM:
            self._trim()

    def _trim(self) -> None:
        lines = self._path.read_text(encoding="utf-8").splitlines(keepends=True)
        lines = lines[-LOG_MAX:]
        self._path.write_text("".join(lines), encoding="utf-8")
        self._count = len(lines)


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self._hwnd: int | None = None
        self._is_active = False
        self._listener = None
        self._pattern: re.Pattern | None = None
        self._last_clip = ""
        self._log: ClipLog | None = None

        root.title("Regex Click Blocker")
        root.resizable(False, False)

        # Window selection
        row = tk.Frame(root, pady=4)
        row.pack(fill=tk.X, padx=10)
        tk.Label(row, text="Window:", width=8, anchor="w").pack(side=tk.LEFT)
        self._window_var = tk.StringVar()
        self._window_combo = ttk.Combobox(row, textvariable=self._window_var, state="readonly", width=38)
        self._window_combo.pack(side=tk.LEFT, padx=(0, 4))
        tk.Button(row, text="↺", command=self._refresh_windows).pack(side=tk.LEFT)

        # Regex
        row2 = tk.Frame(root, pady=4)
        row2.pack(fill=tk.X, padx=10)
        tk.Label(row2, text="Regex:", width=8, anchor="w").pack(side=tk.LEFT)
        self._regex_var = tk.StringVar()
        tk.Entry(row2, textvariable=self._regex_var, width=40).pack(side=tk.LEFT)

        # Invert checkbox
        self._invert_var = tk.BooleanVar()
        tk.Checkbutton(root, text="Block when regex not found", variable=self._invert_var).pack(anchor="w", padx=18)

        # Start/Stop
        self._toggle_btn = tk.Button(root, text="Start", width=12, command=self._on_toggle)
        self._toggle_btn.pack(pady=8)

        # Clipboard display
        row3 = tk.Frame(root, pady=4)
        row3.pack(fill=tk.X, padx=10)
        tk.Label(row3, text="Clipboard:", width=8, anchor="w").pack(side=tk.LEFT)
        self._clipboard_var = tk.StringVar()
        tk.Entry(row3, textvariable=self._clipboard_var, state="readonly", width=40).pack(side=tk.LEFT)

        # Status
        self._status_var = tk.StringVar(value="—")
        tk.Label(root, textvariable=self._status_var, font=("", 9, "italic"), pady=4).pack()

        self._refresh_windows()

    def _refresh_windows(self):
        own = self.root.title()
        titles = sorted({t for t in gw.getAllTitles() if t and t != own})
        self._window_combo["values"] = titles

    def _on_toggle(self):
        if self._is_active:
            self._stop()
        else:
            self._start()

    def _start(self):
        title = self._window_var.get()
        if not title:
            messagebox.showinfo("Error", "Select a window first.")
            return

        pattern_str = self._regex_var.get()
        if not pattern_str:
            messagebox.showinfo("Error", "Enter a regex pattern.")
            return
        try:
            self._pattern = re.compile(pattern_str)
        except re.error as exc:
            messagebox.showinfo("Error", f"Invalid regex: {exc}")
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

    def _stop(self):
        self._is_active = False
        self._stop_listener()
        if platform.system() == "Windows" and self._hwnd:
            win32gui.EnableWindow(self._hwnd, True)
        self._hwnd = None
        self._pattern = None
        self._log = None
        self._toggle_btn.config(text="Start")
        self._status_var.set("Stopped")

    def _start_listener(self):
        hwnd = self._hwnd

        def on_click(x, y, button, pressed):
            if not pressed or not self._is_active:
                return
            # Only refresh clipboard when the target window was enabled, meaning the
            # click went through and likely changed the selection in the target window.
            if platform.system() == "Windows" and hwnd and win32gui.IsWindowEnabled(hwnd):
                self.root.after(0, lambda: pyautogui.hotkey("ctrl", "c"))

        self._listener = mouse.Listener(on_click=on_click)
        self._listener.start()

    def _stop_listener(self):
        if self._listener:
            self._listener.stop()
            self._listener = None

    def _tick(self):
        if not self._is_active:
            return

        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            text = ""

        self._clipboard_var.set(text)

        if self._hwnd is not None and self._pattern is not None:
            matched = bool(self._pattern.search(text))
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


def main():
    root = tk.Tk()
    app = App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
