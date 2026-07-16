"""
E2E smoke test for regex-click-python.

Launches fake_target.py and main.py together, clicks on the fake window,
and asserts that the main app blocks/allows correctly via win32gui.

Requirements: Windows, uv, the venv already set up.
Usage:  uv run test_e2e.py
"""
import json
import subprocess
import sys
import time
from pathlib import Path

if sys.platform != "win32":
    print("E2E tests require Windows.")
    sys.exit(1)

import pyautogui
import win32gui

HERE = Path(__file__).parent

# ── item texts must match fake_target.py's ITEMS list ────────────────────────
ITEM_PLAIN    = 0   # not desirable
ITEM_PACKSIZE = 1   # desirable (Pack Size matches inclusion rule)
ITEM_REFLECT  = 2   # excluded (Reflects matches exclusion rule)

TEST_CONFIG = {
    "window": "FakeStash",
    "advanced": False,
    "ignore_stale": True,
    "groups": [
        {
            "desc": "Pack Size",
            "rows": [{"active": True, "desc": "pack size", "pattern": "Pack Size"}],
        }
    ],
    "exclusions": [
        {"active": True, "desc": "Reflect", "pattern": "Reflects"},
    ],
}

# ── helpers ───────────────────────────────────────────────────────────────────

def find_hwnd(title: str, timeout: float = 6.0) -> int:
    deadline = time.time() + timeout
    while time.time() < deadline:
        hwnd = win32gui.FindWindow(None, title)
        if hwnd:
            return hwnd
        time.sleep(0.1)
    raise RuntimeError(f"Window '{title}' did not appear within {timeout}s")


def center_of(hwnd: int) -> tuple[int, int]:
    lx, ty, rx, by = win32gui.GetWindowRect(hwnd)
    return (lx + rx) // 2, (ty + by) // 2


def click_center(hwnd: int) -> None:
    x, y = center_of(hwnd)
    pyautogui.click(x, y)


def wait_enabled(hwnd: int, enabled: bool, timeout: float = 2.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if bool(win32gui.IsWindowEnabled(hwnd)) == enabled:
            return True
        time.sleep(0.025)
    return False


# ── test cases ────────────────────────────────────────────────────────────────

def test_blocks_on_desirable(target_hwnd: int) -> bool:
    """
    FakeStash starts on item 0 (plain). One click advances to item 1 (Pack Size).
    App should send Ctrl+C, evaluate, find it desirable, and disable FakeStash.
    """
    print("  click → item 1 (Pack Size) …", end=" ", flush=True)
    click_center(target_hwnd)
    ok = wait_enabled(target_hwnd, enabled=False, timeout=2.0)
    print("PASS — FakeStash disabled" if ok else "FAIL — FakeStash still enabled")
    return ok


def test_stays_blocked(target_hwnd: int) -> bool:
    """While blocked, a click attempt should have no effect on the item index."""
    print("  click while blocked → should stay blocked …", end=" ", flush=True)
    click_center(target_hwnd)
    time.sleep(0.1)
    still_disabled = not win32gui.IsWindowEnabled(target_hwnd)
    print("PASS — still blocked" if still_disabled else "FAIL — became enabled")
    return still_disabled


# ── runner ────────────────────────────────────────────────────────────────────

def main():
    config_path = HERE / "config.json"
    original_config = config_path.read_text() if config_path.exists() else None

    passed = 0
    total  = 0
    target_proc = None
    app_proc    = None

    try:
        config_path.write_text(json.dumps(TEST_CONFIG, indent=2))
        print("[setup] wrote test config.json")

        target_proc = subprocess.Popen([sys.executable, HERE / "fake_target.py"])
        target_hwnd = find_hwnd("FakeStash")
        print(f"[setup] FakeStash HWND {target_hwnd:#x}")

        app_proc = subprocess.Popen(
            [sys.executable, HERE / "main.py", "--auto-start"],
        )
        # wait for the app window AND for _start() to finish initialising
        find_hwnd("Regex Click Blocker")
        time.sleep(1.0)
        print("[setup] main app started with --auto-start")

        print("\nRunning tests:")

        for fn in [test_blocks_on_desirable, test_stays_blocked]:
            total += 1
            if fn(target_hwnd):
                passed += 1

    finally:
        if app_proc:
            app_proc.terminate()
        if target_proc:
            target_proc.terminate()
        if original_config is not None:
            config_path.write_text(original_config)
            print("\n[teardown] restored original config.json")
        else:
            config_path.unlink(missing_ok=True)
            print("\n[teardown] removed test config.json")

    print(f"\n{'='*40}")
    print(f"Result: {passed}/{total} passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
