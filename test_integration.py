"""
Integration tests: App clipboard evaluation pipeline.

Creates a real App instance (real tk.Tk, real widgets) and calls
_apply_result() with injected text to test the full evaluation pipeline
without needing a target window, mouse events, or win32gui.

Runs on both macOS (dev) and Windows.
"""
import sys
import pytest
import tkinter as tk
from unittest.mock import patch

# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def root():
    r = tk.Tk()
    r.withdraw()
    yield r
    r.destroy()


def fresh_app(root, tmp_path):
    """App with no config loaded (tmp_path has no config.json)."""
    from main import App
    with patch("main.CONFIG_PATH", tmp_path / "config.json"):
        app = App(root)
    # Remove the default empty group added by __init__
    for g in list(app._groups):
        g.destroy()
    app._groups.clear()
    return app


def setup(app, inclusions: list[str] = (), exclusions: list[str] = ()):
    """Add inclusion rows (one group) and exclusion rows, then compile."""
    if inclusions:
        g = app._add_group()
        # _add_group adds one blank row; overwrite it instead of adding another
        g.rows[0].pattern_var.set(inclusions[0])
        for pat in inclusions[1:]:
            g.add_row({"desc": "", "pattern": pat, "active": True})
    for pat in exclusions:
        app._add_excl_row({"desc": "", "pattern": pat, "active": True})
    app._compile_all()
    return app


def status(app) -> str:
    return app._status_var.get()


# ── single group, inclusion only ──────────────────────────────────────────────

def test_desirable_blocks(root, tmp_path):
    app = setup(fresh_app(root, tmp_path), inclusions=["Pack Size"])
    app._apply_result("Monster Pack Size: +28%\nItem Quantity: +22%")
    assert "Blocked" in status(app)


def test_plain_allows(root, tmp_path):
    app = setup(fresh_app(root, tmp_path), inclusions=["Pack Size"])
    app._apply_result("Item Quantity: +5%\nItem Rarity: +6%")
    assert "Allowed" in status(app)


def test_exclusion_overrides_inclusion(root, tmp_path):
    app = setup(fresh_app(root, tmp_path),
                inclusions=["Pack Size"], exclusions=["Reflects"])
    app._apply_result("Monster Pack Size: +12%\nReflects 14 Physical Damage to Melee Attackers")
    assert "Allowed" in status(app)


def test_exclusion_alone_blocks_when_absent(root, tmp_path):
    """One exclusion row, no inclusion: item is desirable when the excluded term is absent."""
    app = setup(fresh_app(root, tmp_path), exclusions=["Reflects"])
    app._apply_result("Monster Pack Size: +28%")   # no Reflects → desirable
    assert "Blocked" in status(app)


def test_exclusion_alone_allows_when_present(root, tmp_path):
    app = setup(fresh_app(root, tmp_path), exclusions=["Reflects"])
    app._apply_result("Reflects 14 Physical Damage to Melee Attackers")
    assert "Allowed" in status(app)


# ── OR within a group ─────────────────────────────────────────────────────────

def test_or_within_group_either_row_matches(root, tmp_path):
    app = setup(fresh_app(root, tmp_path), inclusions=["Pack Size", "Quantity"])
    app._apply_result("Item Quantity: +22%")   # only Quantity, no Pack Size
    assert "Blocked" in status(app)

    app._apply_result("Monster Pack Size: +28%")  # only Pack Size
    assert "Blocked" in status(app)

    app._apply_result("Item Rarity: +15%")  # neither
    assert "Allowed" in status(app)


# ── AND across groups ─────────────────────────────────────────────────────────

def test_and_across_groups_both_required(root, tmp_path):
    app = fresh_app(root, tmp_path)
    g1 = app._add_group()
    g1.rows[0].pattern_var.set("Pack Size")
    g2 = app._add_group()
    g2.rows[0].pattern_var.set("Quantity")
    app._compile_all()

    app._apply_result("Monster Pack Size: +28%")   # Pack Size but no Quantity
    assert "Allowed" in status(app)

    app._apply_result("Monster Pack Size: +28%\nItem Quantity: +22%")  # both
    assert "Blocked" in status(app)


# ── disabled rows ─────────────────────────────────────────────────────────────

def test_disabled_row_is_ignored(root, tmp_path):
    app = fresh_app(root, tmp_path)
    g = app._add_group()
    g.rows[0].pattern_var.set("Pack Size")
    g.rows[0].active_var.set(False)
    g.rows[0]._toggle_btn.config(text="○", fg="#888888")
    app._compile_all()

    app._apply_result("Monster Pack Size: +28%")
    assert "Allowed" in status(app)   # disabled → no active patterns → not desirable


# ── split / merge round-trip ──────────────────────────────────────────────────

def test_split_then_merge_same_result(root, tmp_path):
    """Splitting 'green blue' into two rows then merging back is a no-op for evaluation."""
    from main import _tokenize_pattern

    app_combined = setup(fresh_app(root, tmp_path), inclusions=["green blue"])
    app_split    = fresh_app(root, tmp_path)
    g = app_split._add_group()
    g.rows[0].pattern_var.set("green")
    g.add_row({"desc": "", "pattern": "blue", "active": True})
    app_split._compile_all()

    for text in ["has green in it", "has blue in it", "has neither"]:
        app_combined._apply_result(text)
        combined_status = status(app_combined)
        app_split._apply_result(text)
        split_status = status(app_split)
        assert ("Blocked" in combined_status) == ("Blocked" in split_status), (
            f"Mismatch for {text!r}: combined={combined_status!r}, split={split_status!r}"
        )
