@echo off
setlocal enabledelayedexpansion

:: ── 1. Ensure uv ──────────────────────────────────────────────────────────────
where uv >nul 2>&1
if !errorlevel! neq 0 (
    echo uv not found - installing...
    winget install astral-sh.uv -e --accept-source-agreements --accept-package-agreements --silent >nul 2>&1
    if !errorlevel! neq 0 (
        :: Fallback: PowerShell one-liner  irm https://astral.sh/uv/install.ps1 | iex
        powershell -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
        if !errorlevel! neq 0 (
            echo uv install failed. Run manually: powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
            pause & exit /b 1
        )
    )
    :: winget/installer update the registry but not this session's PATH
    set "PATH=%LOCALAPPDATA%\uv\bin;%PATH%"
    where uv >nul 2>&1
    if !errorlevel! neq 0 (
        echo uv installed. Please close this window and run run.bat again.
        pause & exit /b 0
    )
)

:: ── 2. Remove stale venv (lib64 symlink from non-Windows checkout causes access-denied) ──
if exist .venv\lib64 (
    echo Removing stale virtual environment...
    rmdir /s /q .venv 2>nul
)

:: ── 3. Ensure Python with tkinter ─────────────────────────────────────────────
uv run python -c "import tkinter" >nul 2>&1
if !errorlevel! equ 0 goto :run

echo tkinter not found - installing Python 3.14 from python.org via winget...
winget install Python.Python.3.14 -e --accept-source-agreements --accept-package-agreements
if !errorlevel! neq 0 (
    echo winget failed. Install Python 3.14 from https://www.python.org/downloads/
    echo During install, check "Add Python to PATH".
    pause & exit /b 1
)
:: Try the common per-user install path before asking for a reopen
set "PATH=%LOCALAPPDATA%\Programs\Python\Python314;%PATH%"
uv run python -c "import tkinter" >nul 2>&1
if !errorlevel! neq 0 (
    echo Python installed. Please close this window and run run.bat again.
    pause & exit /b 0
)

:: ── 4. Run ────────────────────────────────────────────────────────────────────
:run
uv run main.py
