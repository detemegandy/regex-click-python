import tkinter as tk
from tkinter import messagebox
from typing import Callable
import pygetwindow as gw
import pyautogui
import platform
from pynput import mouse

if platform.system() == "Windows":
    import win32gui


def find_windows(title_part: str) -> list[str]:
    if not title_part:
        return []
    return [w for w in gw.getAllTitles() if title_part in w and w]


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
        self._is_blocking = False
        self._listener = None

        self._monitor = ClipboardMonitor(root, self._show_clipboard)

        root.title("Cross-Platform UI")

        self._entry_var = tk.StringVar()
        self._entry = tk.Entry(root, textvariable=self._entry_var)
        self._entry.pack(pady=10)

        self._toggle_btn = tk.Button(root, text="Start", command=self._on_toggle)
        self._toggle_btn.pack(pady=10)

        self._clipboard_var = tk.StringVar()
        tk.Entry(root, textvariable=self._clipboard_var, state="readonly", font=("italic", 10)).pack(pady=10)

    def _on_toggle(self):
        if self._is_blocking:
            self._stop()
        else:
            self._start()

    def _start(self):
        titles = find_windows(self._entry_var.get())
        if len(titles) != 1:
            self._entry.config(fg="red")
            if not titles:
                messagebox.showinfo("Error", "No matching windows found.")
            else:
                messagebox.showinfo("Error", "More than one matching window found.")
            return

        windows = gw.getWindowsWithTitle(titles[0])
        if not windows:
            messagebox.showinfo("Error", "Window closed before it could be selected.")
            return

        if platform.system() == "Windows":
            self._hwnd = windows[0]._hWnd
            win32gui.EnableWindow(self._hwnd, False)

        self._start_listener()
        self._is_blocking = True
        self._toggle_btn.config(text="Stop")
        self._entry.config(fg="black")
        messagebox.showinfo("Selected Window", f"You selected: {titles[0]}. Mouse clicks are now blocked.")

    def _stop(self):
        # Set flag before stopping listener so any queued after(0,...) callbacks
        # see _is_blocking=False and bail out without firing Ctrl+C.
        self._is_blocking = False
        self._stop_listener()
        if platform.system() == "Windows" and self._hwnd:
            win32gui.EnableWindow(self._hwnd, True)
        self._hwnd = None
        self._toggle_btn.config(text="Start")
        messagebox.showinfo("Selected Window", "Mouse clicks are now unblocked.")

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
        if not self._is_blocking:
            return
        # SetForegroundWindow is intentionally absent: calling it on a
        # disabled window flickered the enabled/disabled state on alternate
        # clicks, letting every other click through.
        pyautogui.hotkey("ctrl", "c")
        self._monitor.schedule_capture()

    def _show_clipboard(self, text: str):
        self._clipboard_var.set(text if text else "null")


def main():
    root = tk.Tk()
    app = App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
