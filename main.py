import tkinter as tk
from tkinter import messagebox
import pygetwindow as gw
import pyautogui
import platform
from pynput import mouse

if platform.system() == "Windows":
    import win32gui
    import win32con

class App:
    def __init__(self, root):
        self.root = root
        self.is_blocking = False
        self.listener = None

        self.root.title("Cross-Platform UI")

        # Text box for entering window title part
        self.entry_var = tk.StringVar()
        self.entry = tk.Entry(root, textvariable=self.entry_var)
        self.entry.pack(pady=10)

        self.toggle_button = tk.Button(root, text="Start", command=self.on_toggle_click)
        self.toggle_button.pack(pady=10)

        # Read-only text box for displaying clipboard content
        self.clipboard_content = tk.StringVar()
        self.clipboard_display = tk.Entry(root, textvariable=self.clipboard_content, state='readonly', font=('italic', 10))
        self.clipboard_display.pack(pady=10)

    def on_toggle_click(self):
        title_part = self.entry_var.get()
        matching_windows = [w for w in gw.getAllTitles() if title_part in w]

        if len(matching_windows) == 1:
            window = gw.getWindowsWithTitle(matching_windows[0])[0]
            hwnd = window._hWnd
            if not self.is_blocking:
                if platform.system() == "Windows":
                    win32gui.EnableWindow(hwnd, False)
                    self.start_mouse_listener(hwnd)
                self.toggle_button.config(text="Stop")
                messagebox.showinfo("Selected Window", f"You selected: {matching_windows[0]}. Mouse clicks are now blocked.")
            else:
                if platform.system() == "Windows":
                    win32gui.EnableWindow(hwnd, True)
                    self.stop_mouse_listener()
                self.toggle_button.config(text="Start")
                messagebox.showinfo("Selected Window", f"Mouse clicks are now unblocked for: {matching_windows[0]}.")
            self.is_blocking = not self.is_blocking
            self.entry.config(fg="black")
        else:
            self.entry.config(fg="red")
            if len(matching_windows) == 0:
                messagebox.showinfo("Error", "No matching windows found.")
            else:
                messagebox.showinfo("Error", "More than one matching window found.")

    def start_mouse_listener(self, hwnd):
        def on_click(x, y, button, pressed):
            if pressed:
                if platform.system() == "Windows":
                    win32gui.SetForegroundWindow(hwnd)
                    pyautogui.hotkey('ctrl', 'c')
                    self.update_clipboard_content()

        self.listener = mouse.Listener(on_click=on_click)
        self.listener.start()

    def stop_mouse_listener(self):
        if self.listener:
            self.listener.stop()
            self.listener = None

    def update_clipboard_content(self):
        self.root.after(1000, self.check_clipboard)

    def check_clipboard(self):
        clipboard_text = self.root.clipboard_get()
        if clipboard_text:
            self.clipboard_content.set(clipboard_text)
        else:
            self.clipboard_content.set("null")
            self.clipboard_display.config(font=('italic', 10))

def main():
    root = tk.Tk()
    app = App(root)
    root.mainloop()

if __name__ == "__main__":
    main()
