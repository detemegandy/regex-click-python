# regex-click-python

## What it does

A tkinter desktop app (Windows-only at runtime) that lets you:
1. Find a window by substring match on its title.
2. Toggle mouse-click blocking on that window via `win32gui.EnableWindow`.
3. On each click into that window, auto-copy the selection (`Ctrl+C`) and show the clipboard contents in the app.

Entry point: `main.py` → `App` class → `main()`.

## Stack

- **Python 3.14** (`.python-version`)
- **uv** for dependency management (`pyproject.toml` + `uv.lock`)
- **tkinter** — UI
- **pygetwindow** — window enumeration/lookup
- **pynput** — global mouse listener (background thread)
- **pyautogui** — sends `Ctrl+C` hotkey
- **pywin32** (`win32gui`) — enables/disables windows (Windows only)

## File map

| File | Purpose |
|---|---|
| `main.py` | Entire app — `App` class + `main()` |
| `pyproject.toml` | Project metadata and dependencies |
| `uv.lock` | Locked dependency graph |
| `.python-version` | Pins Python 3.14 for uv |

## Known issues

- **Windows-only at runtime**: `window._hWnd` and `win32gui` are only valid on Windows. The platform guard is correct; `_hWnd` is only accessed inside `platform.system() == "Windows"` branches.

## Running

### Windows

Double-click `run.bat` or run it from a terminal. It will:
1. Check if tkinter is available
2. If not, auto-install Python 3.14 from python.org via `winget` (includes tkinter)
3. Launch the app

`uv` must be installed first: https://docs.astral.sh/uv/

### Windows machine layout

The Windows machine has a related repo at `C:\repos\regex-click` — the C# WinForms predecessor to this app. Use `ssh windows "powershell -command '...'"` from the Mac to inspect or run commands there.

### macOS (dev only — app will not function fully)

tkinter is not a pip package on macOS; install it via Homebrew before `uv run`:

```bash
brew install python-tk@3.14
uv run main.py
```
