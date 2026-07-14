@echo off
setlocal enabledelayedexpansion

where uv >nul 2>&1
if !errorlevel! neq 0 (
    echo uv is not installed. Get it from: https://docs.astral.sh/uv/
    pause
    exit /b 1
)

uv run python -c "import tkinter" >nul 2>&1
if !errorlevel! equ 0 goto :run

echo tkinter not found - installing Python 3.14 from python.org via winget...
winget install Python.Python.3.14 -e --accept-source-agreements --accept-package-agreements
if !errorlevel! neq 0 (
    echo.
    echo Auto-install failed. Install Python 3.14 manually from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

:run
uv run main.py
