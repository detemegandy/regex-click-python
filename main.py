import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable
import re
import pygetwindow as gw
import pyautogui
import platform
from pynput import mouse

if platform.system() == "Windows":
    import win32gui


class ClipboardMonitor:
    def __init__(self, root: tk.Tk, on_result: Callable[[str], None]):
        self._root = root
        self._on_result = on_result
        self._pending = False

    def schedule_capture(self) -> None:
        if self._pending:
            return
        self._pending = True
        self._root.after(1000, self._read)

    def _read(self) -> None:
        self._pending = False
        try:
            text = self._root.clipboard_get()
        except tk.TclError:
            text = ""
        self._on_result(text)


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self._hwnd = None
        self._is_active = False
        self._listener = None
        self._pattern: re.Pattern | None = None

        self._monitor = ClipboardMonitor(root, self._on_clipboard)

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

        self._is_active = True
        self._toggle_btn.config(text="Stop")
        self._status_var.set("Monitoring — click in target window to test")
        self._start_listener()

    def _stop(self):
        # Set flag before stopping listener so queued callbacks see it and bail.
        self._is_active = False
        self._stop_listener()
        if platform.system() == "Windows" and self._hwnd:
            win32gui.EnableWindow(self._hwnd, True)
        self._hwnd = None
        self._pattern = None
        self._toggle_btn.config(text="Start")
        self._status_var.set("Stopped")

    def _start_listener(self):
        def on_click(x, y, button, pressed):
            if pressed:
                # Dispatch to main thread — pyautogui must never run inside a
                # low-level hook callback (causes OS message-pump deadlock).
                self.root.after(0, self._copy_selection)

        self._listener = mouse.Listener(on_click=on_click)
        self._listener.start()

    def _stop_listener(self):
        if self._listener:
            self._listener.stop()
            self._listener = None

    def _copy_selection(self):
        # Guard against a queued after(0,...) firing after Stop was clicked.
        if not self._is_active:
            return
        # SetForegroundWindow is intentionally absent: calling it on a
        # disabled window flickered the enabled/disabled state on alternate
        # clicks, letting every other click through.
        pyautogui.hotkey("ctrl", "c")
        self._monitor.schedule_capture()

    def _on_clipboard(self, text: str):
        self._clipboard_var.set(text)
        if not self._is_active or self._hwnd is None or self._pattern is None:
            return

        matched = bool(self._pattern.search(text))
        should_block = matched if not self._invert_var.get() else not matched

        if platform.system() == "Windows":
            win32gui.EnableWindow(self._hwnd, not should_block)

        action = "BLOCKED" if should_block else "unblocked"
        reason = "regex found" if matched else "regex not found"
        self._status_var.set(f"{action} — {reason}")


def main():
    root = tk.Tk()
    app = App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
