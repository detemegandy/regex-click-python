import json
import sys
import time
import tkinter as tk
from tkinter import messagebox, ttk
import re
import subprocess
import pygetwindow as gw
import pyautogui
import platform
from datetime import datetime
from pathlib import Path
from typing import NamedTuple
from pynput import mouse

IS_WINDOWS = platform.system() == "Windows"

if IS_WINDOWS:
    import win32gui

pyautogui.FAILSAFE = False  # prevent FailSafeException from killing the tick chain


def format_regex_pattern(text: str) -> str:
    """Convert space-separated words / quoted phrases to a regex alternation.

    'apple "orange juice"' → 'apple|orange\\ juice'  (each part re.escaped)
    Raises ValueError on unmatched quotes.
    """
    parts: list[str] = []
    i = 0
    while i < len(text):
        if text[i] == '"':
            end = text.find('"', i + 1)
            if end == -1:
                raise ValueError("Unmatched quotation mark")
            phrase = text[i + 1:end].strip()
            if phrase:
                parts.append(re.escape(phrase))
            i = end + 1
        elif text[i] == ' ':
            i += 1
        else:
            end = i
            while end < len(text) and text[end] not in (' ', '"'):
                end += 1
            word = text[i:end]
            if word:
                parts.append(re.escape(word))
            i = end
    if not parts:
        return ""
    return "|".join(parts)


def _tokenize_pattern(text: str) -> list[str]:
    """Inverse of format_regex_pattern: split easy-mode input into individual terms."""
    tokens: list[str] = []
    s = text.strip()
    while s:
        if s.startswith('"'):
            end = s.find('"', 1)
            if end == -1:
                tokens.append(s)
                break
            phrase = s[1:end]
            if phrase:
                tokens.append(f'"{phrase}"')
            s = s[end + 1:].lstrip()
        else:
            word, _, rest = s.partition(" ")
            if word:
                tokens.append(word)
            s = rest.lstrip()
    return tokens


POLL_MS      = 25
LOG_MAX      = 30_000
LOG_HEADROOM = 1_000
LOG_PATH     = Path(__file__).parent / "clip_log.txt"
CONFIG_PATH  = Path(__file__).parent / "config.json"
VIEWER_LIMIT = 500


class LogEntry(NamedTuple):
    ts:     str
    action: str
    reason: str
    clip:   str


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
        line = f"{ts} | {action:<11} | {reason:<28} | {safe}\n"
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


def _last_logged_clip() -> str:
    """Return clipboard text from the last non-SESSION log entry."""
    if not LOG_PATH.exists():
        return ""
    for line in reversed(LOG_PATH.read_text(encoding="utf-8").splitlines()):
        parts = line.split(" | ", 3)
        if len(parts) == 4 and parts[1].strip() != "SESSION":
            return parts[3].strip()
    return ""


# ── LogViewer ─────────────────────────────────────────────────────────────────

class LogViewer(tk.Toplevel):
    def __init__(self, parent: tk.Tk, log_path: Path):
        super().__init__(parent)
        self._log_path = log_path
        self._all_entries: list[LogEntry] = []
        self._auto_var = tk.BooleanVar(value=True)

        self.title("Clipboard Log")
        self.geometry("1100x520")
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
                     values=["All", "BLOCKED", "allowed", "unblocked", "SESSION"],
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
        self._tree.column("reason", width=220, stretch=False)
        self._tree.column("clip",   width=560)
        vsb = ttk.Scrollbar(frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._tree.tag_configure("blocked",  background="#ffd6d6")
        self._tree.tag_configure("allowed",  background="#d6ffd6")
        self._tree.tag_configure("session",  background="#d6e8ff")

        self._bar_var = tk.StringVar()
        tk.Label(self, textvariable=self._bar_var, anchor="w",
                 font=("", 8)).pack(fill=tk.X, padx=8, pady=(0, 4))

        self._load()
        self._schedule_refresh()

    def _load(self) -> None:
        if not self._log_path.exists():
            self._bar_var.set("No log file yet.")
            return
        entries: list[LogEntry] = []
        for line in self._log_path.read_text(encoding="utf-8").splitlines():
            parts = line.split(" | ", 3)
            if len(parts) == 4:
                entries.append(LogEntry(*(p.strip() for p in parts)))
        self._all_entries = entries
        self._apply_filter()

    def _apply_filter(self) -> None:
        text_f   = self._filter_var.get().lower()
        status_f = self._status_filter.get()
        entries  = self._all_entries
        if status_f != "All":
            entries = [e for e in entries if e.action == status_f]
        if text_f:
            entries = [e for e in entries if text_f in e.clip.lower() or text_f in e.ts]
        shown = entries[-VIEWER_LIMIT:]
        self._tree.delete(*self._tree.get_children())
        for e in shown:
            if e.action == "BLOCKED":
                tag = "blocked"
            elif e.action == "SESSION":
                tag = "session"
            else:
                tag = "allowed"
            self._tree.insert("", "end", values=(e.ts, e.action, e.reason, e.clip), tags=(tag,))
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
    """One pattern. polarity '+' lives inside a group; '-' is a standalone exclusion."""

    def __init__(self, parent: tk.Frame, polarity: str, on_remove, on_change, on_split=None):
        self._polarity  = polarity
        self._on_change = on_change
        self.active_var  = tk.BooleanVar(value=True)
        self.desc_var    = tk.StringVar()
        self.pattern_var = tk.StringVar()
        self.compiled: re.Pattern | None = None

        self._frame = tk.Frame(parent)
        self._frame.pack(fill=tk.X, pady=1)

        self._active_fg = "#1a7f37" if polarity == "+" else "#cf222e"
        self._toggle_btn = tk.Button(
            self._frame,
            text=polarity,
            width=2,
            font=("", 10, "bold"),
            fg=self._active_fg,
            relief=tk.FLAT,
            command=self._toggle,
        )
        self._toggle_btn.pack(side=tk.LEFT, padx=(0, 2))

        tk.Entry(self._frame, textvariable=self.desc_var,    width=18).pack(side=tk.LEFT, padx=2)
        self._pat_entry = tk.Entry(self._frame, textvariable=self.pattern_var, width=28)
        self._pat_entry.pack(side=tk.LEFT, padx=2)
        if on_split is not None:
            tk.Button(self._frame, text="split", fg="#666666", font=("", 8),
                      command=lambda: on_split(self)).pack(side=tk.LEFT, padx=2)
        tk.Button(self._frame, text="×", width=2, command=lambda: on_remove(self)).pack(side=tk.LEFT, padx=2)

        self.desc_var.trace_add("write",    lambda *_: on_change())
        self.pattern_var.trace_add("write", lambda *_: on_change())

    def _toggle(self) -> None:
        active = not self.active_var.get()
        self.active_var.set(active)
        self._toggle_btn.config(
            text=self._polarity if active else "○",
            fg=self._active_fg if active else "#888888",
        )
        self._on_change()

    def compile(self, advanced: bool) -> str | None:
        """Compile in-place. Returns error string or None on success."""
        self.mark_error(False)
        self.compiled = None
        if not self.active_var.get() or not self.pattern_var.get():
            return None
        try:
            pat = self.pattern_var.get()
            if not advanced:
                pat = format_regex_pattern(pat)
                self.compiled = re.compile(pat, re.IGNORECASE)
            else:
                self.compiled = re.compile(pat)
            return None
        except (re.error, ValueError) as exc:
            self.mark_error(True)
            label = self.desc_var.get() or self.pattern_var.get()
            return f'"{label}": {exc}'

    def mark_error(self, error: bool) -> None:
        self._pat_entry.config(bg="#ffd6d6" if error else "white")

    def destroy(self) -> None:
        self._frame.destroy()

    def to_dict(self) -> dict:
        return {
            "active":  self.active_var.get(),
            "desc":    self.desc_var.get(),
            "pattern": self.pattern_var.get(),
        }

    def load(self, d: dict) -> None:
        active = d.get("active", d.get("enabled", True))
        self.active_var.set(active)
        self._toggle_btn.config(
            text=self._polarity if active else "○",
            fg=self._active_fg if active else "#888888",
        )
        self.desc_var.set(d.get("desc", ""))
        self.pattern_var.set(d.get("pattern", ""))


# ── PatternGroup ──────────────────────────────────────────────────────────────

class PatternGroup:
    """Named group of + rows. Desirable if any active row matches (OR within group)."""

    def __init__(self, parent: tk.Frame, on_remove, on_change):
        self._on_change = on_change
        self.desc_var   = tk.StringVar()
        self.rows: list[PatternRow] = []

        self._frame = tk.Frame(parent, relief=tk.GROOVE, bd=1, padx=4, pady=3)
        self._frame.pack(fill=tk.X, pady=2)

        hdr = tk.Frame(self._frame)
        hdr.pack(fill=tk.X, pady=(0, 2))
        tk.Label(hdr, text="Group:", fg="#1a7f37", font=("", 9, "bold")).pack(side=tk.LEFT)
        tk.Entry(hdr, textvariable=self.desc_var, width=22).pack(side=tk.LEFT, padx=(4, 0))
        tk.Button(hdr, text="Remove group", fg="#888888",
                  command=lambda: on_remove(self)).pack(side=tk.RIGHT)
        tk.Button(hdr, text="merge", fg="#666666", font=("", 8),
                  command=self._merge_rows).pack(side=tk.RIGHT, padx=(0, 4))

        self._rows_frame = tk.Frame(self._frame)
        self._rows_frame.pack(fill=tk.X)

        tk.Button(self._frame, text="+ row", fg="#1a7f37",
                  command=lambda: self.add_row()).pack(anchor="e", pady=(2, 0))

        self.desc_var.trace_add("write", lambda *_: on_change())

    def add_row(self, data: dict | None = None) -> PatternRow:
        row = PatternRow(self._rows_frame, "+", self._remove_row, self._on_change,
                         on_split=self._split_row)
        if data:
            row.load(data)
        self.rows.append(row)
        self._on_change()
        return row

    def _remove_row(self, row: PatternRow) -> None:
        if len(self.rows) <= 1:
            return
        row.destroy()
        self.rows.remove(row)
        self._on_change()

    def _split_row(self, row: PatternRow) -> None:
        tokens = _tokenize_pattern(row.pattern_var.get())
        if len(tokens) <= 1:
            return
        desc = row.desc_var.get()
        row.destroy()
        self.rows.remove(row)
        for i, token in enumerate(tokens):
            new_row = self.add_row()
            new_row.desc_var.set(desc if i == 0 else "")
            new_row.pattern_var.set(token)

    def _merge_rows(self) -> None:
        if len(self.rows) <= 1:
            return
        combined = " ".join(r.pattern_var.get() for r in self.rows if r.pattern_var.get())
        desc = next((r.desc_var.get() for r in self.rows if r.desc_var.get()), "")
        for row in self.rows:
            row.destroy()
        self.rows.clear()
        new_row = PatternRow(self._rows_frame, "+", self._remove_row, self._on_change,
                             on_split=self._split_row)
        new_row.desc_var.set(desc)
        new_row.pattern_var.set(combined)
        self.rows.append(new_row)
        self._on_change()

    def is_desirable(self, text: str) -> bool:
        active = [r for r in self.rows if r.active_var.get() and r.compiled]
        return bool(active) and any(r.compiled.search(text) for r in active)

    def match_count(self, text: str) -> tuple[int, int]:
        active  = [r for r in self.rows if r.active_var.get() and r.compiled]
        matched = sum(1 for r in active if r.compiled.search(text))
        return matched, len(active)

    def compile(self, advanced: bool) -> list[str]:
        return [err for r in self.rows if (err := r.compile(advanced)) is not None]

    def destroy(self) -> None:
        self._frame.destroy()

    def to_dict(self) -> dict:
        return {"desc": self.desc_var.get(), "rows": [r.to_dict() for r in self.rows]}

    def load(self, d: dict) -> None:
        self.desc_var.set(d.get("desc", ""))
        for rd in d.get("rows", []):
            self.add_row(rd)


# ── App ───────────────────────────────────────────────────────────────────────

class App:
    def __init__(self, root: tk.Tk):
        self.root        = root
        self._hwnd: int | None = None
        self._is_active  = False
        self._listener   = None
        self._groups: list[PatternGroup] = []
        self._excl_rows: list[PatternRow] = []
        self._last_clip  = ""
        self._log: ClipLog | None = None
        self._viewer: LogViewer | None = None
        self._save_after: str | None = None
        self._should_ctrl_c = False
        self._ctrl_c_at: float | None = None
        self._last_was_desirable = False

        root.title("Regex Click Blocker")
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        # ── window selection ──────────────────────────────────────────────────
        wr = tk.Frame(root, pady=4)
        wr.pack(fill=tk.X, padx=10)
        tk.Label(wr, text="Window:", width=8, anchor="w").pack(side=tk.LEFT)
        self._window_var = tk.StringVar()
        self._window_var.trace_add("write", lambda *_: self._schedule_save())
        self._window_combo = ttk.Combobox(wr, textvariable=self._window_var,
                                          state="readonly", width=36)
        self._window_combo.pack(side=tk.LEFT, padx=(0, 4))
        tk.Button(wr, text="↺", command=self._refresh_windows).pack(side=tk.LEFT)

        # ── Must Have (groups) ────────────────────────────────────────────────
        mh = tk.LabelFrame(root, text="Must Have  (+)", padx=6, pady=4,
                           fg="#1a7f37", font=("", 9, "bold"))
        mh.pack(fill=tk.X, padx=10, pady=(6, 2))
        self._groups_frame = tk.Frame(mh)
        self._groups_frame.pack(fill=tk.X)
        tk.Button(mh, text="+ Add group", fg="#1a7f37",
                  command=self._add_group).pack(anchor="e", pady=(4, 0))

        # ── Must Not Have (exclusions) ────────────────────────────────────────
        mn = tk.LabelFrame(root, text="Must Not Have  (−)", padx=6, pady=4,
                           fg="#cf222e", font=("", 9, "bold"))
        mn.pack(fill=tk.X, padx=10, pady=(2, 6))
        excl_hdr = tk.Frame(mn)
        excl_hdr.pack(fill=tk.X)
        tk.Label(excl_hdr, text="−", width=3, fg="#cf222e",
                 font=("", 10, "bold")).pack(side=tk.LEFT)
        tk.Label(excl_hdr, text="Description", width=18, anchor="w").pack(side=tk.LEFT, padx=2)
        self._excl_pat_label = tk.Label(excl_hdr, text="Words / Phrases",
                                        width=28, anchor="w")
        self._excl_pat_label.pack(side=tk.LEFT, padx=2)
        self._excl_frame = tk.Frame(mn)
        self._excl_frame.pack(fill=tk.X)
        tk.Button(mn, text="− Add exclusion", fg="#cf222e",
                  command=self._add_excl_row).pack(anchor="e", pady=(4, 0))

        # ── options ───────────────────────────────────────────────────────────
        opt = tk.Frame(root)
        opt.pack(fill=tk.X, padx=14, pady=(0, 4))
        self._advanced_var = tk.BooleanVar()
        self._advanced_var.trace_add("write", lambda *_: self._on_advanced_change())
        tk.Checkbutton(opt, text="Advanced regex (raw)",
                       variable=self._advanced_var).pack(anchor="w")
        self._ignore_stale_var = tk.BooleanVar()
        self._ignore_stale_var.trace_add("write", lambda *_: self._schedule_save())
        tk.Checkbutton(opt, text="Ignore stale clipboard",
                       variable=self._ignore_stale_var).pack(anchor="w")

        # ── buttons ───────────────────────────────────────────────────────────
        btn = tk.Frame(root)
        btn.pack(pady=8)
        self._toggle_btn = tk.Button(btn, text="Start", width=12, command=self._on_toggle)
        self._toggle_btn.pack(side=tk.LEFT, padx=4)
        tk.Button(btn, text="Open Log", width=10, command=self._open_log).pack(side=tk.LEFT, padx=4)

        # ── clipboard display ─────────────────────────────────────────────────
        cr = tk.Frame(root, pady=4)
        cr.pack(fill=tk.X, padx=10)
        tk.Label(cr, text="Clipboard:", width=8, anchor="w").pack(side=tk.LEFT)
        self._clipboard_var = tk.StringVar()
        tk.Entry(cr, textvariable=self._clipboard_var,
                 state="readonly", width=40).pack(side=tk.LEFT)

        self._status_var = tk.StringVar(value="—")
        tk.Label(root, textvariable=self._status_var,
                 font=("", 9, "italic"), pady=4, wraplength=500, justify="left").pack()

        self._refresh_windows()
        self._load_config()
        if not self._groups:
            self._add_group()

    # ── pattern management ────────────────────────────────────────────────────

    def _add_group(self, data: dict | None = None) -> PatternGroup:
        group = PatternGroup(self._groups_frame, self._remove_group, self._schedule_save)
        if data:
            group.load(data)
        else:
            group.add_row()
        self._groups.append(group)
        self._schedule_save()
        return group

    def _remove_group(self, group: PatternGroup) -> None:
        if len(self._groups) <= 1:
            return
        group.destroy()
        self._groups.remove(group)
        self._schedule_save()

    def _add_excl_row(self, data: dict | None = None) -> PatternRow:
        row = PatternRow(self._excl_frame, "-", self._remove_excl_row, self._schedule_save)
        if data:
            row.load(data)
        self._excl_rows.append(row)
        self._schedule_save()
        return row

    def _remove_excl_row(self, row: PatternRow) -> None:
        row.destroy()
        self._excl_rows.remove(row)
        self._schedule_save()

    def _on_advanced_change(self) -> None:
        self._excl_pat_label.config(
            text="Regex" if self._advanced_var.get() else "Words / Phrases"
        )
        self._schedule_save()

    # ── config ────────────────────────────────────────────────────────────────

    def _load_config(self) -> None:
        if not CONFIG_PATH.exists():
            return
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return
        self._window_var.set(cfg.get("window", ""))
        self._advanced_var.set(cfg.get("advanced", False))
        self._ignore_stale_var.set(cfg.get("ignore_stale", False))
        for gd in cfg.get("groups", []):
            self._add_group(gd)
        for ed in cfg.get("exclusions", []):
            self._add_excl_row(ed)
        # Migrate old flat-patterns format
        if not cfg.get("groups") and cfg.get("patterns"):
            if cfg.get("invert", False):
                for pd in cfg["patterns"]:
                    self._add_excl_row(pd)
            else:
                g = self._add_group()
                for pd in cfg["patterns"]:
                    g.add_row(pd)

    def _schedule_save(self) -> None:
        if self._save_after:
            self.root.after_cancel(self._save_after)
        self._save_after = self.root.after(500, self._save_config)

    def _save_config(self) -> None:
        self._save_after = None
        cfg = {
            "window":       self._window_var.get(),
            "advanced":     self._advanced_var.get(),
            "ignore_stale": self._ignore_stale_var.get(),
            "groups":       [g.to_dict() for g in self._groups],
            "exclusions":   [r.to_dict() for r in self._excl_rows],
        }
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    def _refresh_windows(self) -> None:
        own = self.root.title()
        titles = sorted({t for t in gw.getAllTitles() if t and t != own})
        self._window_combo["values"] = titles

    # ── evaluation ────────────────────────────────────────────────────────────

    def _compile_all(self) -> list[str]:
        advanced = self._advanced_var.get()
        errors: list[str] = []
        for g in self._groups:
            errors.extend(g.compile(advanced))
        for r in self._excl_rows:
            if (err := r.compile(advanced)) is not None:
                errors.append(err)
        return errors

    def _has_any_active(self) -> bool:
        for g in self._groups:
            if any(r.active_var.get() and r.compiled for r in g.rows):
                return True
        return any(r.active_var.get() and r.compiled for r in self._excl_rows)

    def _is_desirable(self, text: str) -> bool:
        """True when item satisfies all criteria → should block."""
        active_groups = [g for g in self._groups
                         if any(r.active_var.get() and r.compiled for r in g.rows)]
        for g in active_groups:
            if not g.is_desirable(text):
                return False
        for r in self._excl_rows:
            if r.active_var.get() and r.compiled and r.compiled.search(text):
                return False
        # Require at least one active pattern to trigger a block
        has_excl = any(r.active_var.get() and r.compiled for r in self._excl_rows)
        return bool(active_groups or has_excl)

    def _eval_reason(self, text: str) -> str:
        parts: list[str] = []
        for i, g in enumerate(self._groups, 1):
            active = [r for r in g.rows if r.active_var.get() and r.compiled]
            if not active:
                continue
            matched = sum(1 for r in active if r.compiled.search(text))
            label   = g.desc_var.get() or f"group{i}"
            parts.append(f"+{label} {matched}/{len(active)}")
        for r in self._excl_rows:
            if r.active_var.get() and r.compiled:
                label = r.desc_var.get() or r.pattern_var.get()[:16]
                hit   = bool(r.compiled.search(text))
                parts.append(f"-{label} {'found' if hit else 'absent'}")
        return "; ".join(parts) if parts else "—"

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

        errors = self._compile_all()
        if errors:
            messagebox.showinfo("Invalid pattern", "\n".join(errors))
            return
        if not self._has_any_active():
            messagebox.showinfo("Error", "No active patterns.")
            return

        windows = gw.getWindowsWithTitle(title)
        if not windows:
            messagebox.showinfo("Error", "Window not found — refresh and try again.")
            return

        if IS_WINDOWS:
            self._hwnd = windows[0]._hWnd

        try:
            clip = self.root.clipboard_get()
        except tk.TclError:
            clip = ""

        # Stale clipboard guard
        if not self._ignore_stale_var.get():
            last = _last_logged_clip()
            if last and clip == last:
                messagebox.showwarning(
                    "Stale clipboard",
                    "The clipboard matches your last session's last item.\n\n"
                    "Stop, copy a fresh item in the target window, then Start again.\n\n"
                    "Tick 'Ignore stale clipboard' to skip this check."
                )
                self._hwnd = None
                return

        self._log           = ClipLog(LOG_PATH)
        self._should_ctrl_c = False
        self._is_active     = True
        self._toggle_btn.config(text="Stop")

        # Log session start with active pattern summary
        advanced = self._advanced_var.get()
        mode     = "[raw]" if advanced else "[easy]"
        g_labels = " | ".join(
            g.desc_var.get() or f"group{i}"
            for i, g in enumerate(self._groups, 1)
            if any(r.active_var.get() and r.compiled for r in g.rows)
        )
        e_labels = " | ".join(
            r.desc_var.get() or r.pattern_var.get()
            for r in self._excl_rows if r.active_var.get() and r.compiled
        )
        summary = "; ".join(filter(None, [
            f"+[{g_labels}]" if g_labels else "",
            f"-[{e_labels}]" if e_labels else "",
            mode,
        ]))
        self._log.write(summary, "SESSION", "start")

        # Window always starts disabled; enable only if clipboard passes
        if IS_WINDOWS and self._hwnd:
            win32gui.EnableWindow(self._hwnd, False)

        self._last_clip = clip
        self._clipboard_var.set(clip)

        if clip:
            desirable = self._is_desirable(clip)
            reason    = self._eval_reason(clip)
            if desirable:
                self._status_var.set(
                    "Blocked — item on clipboard already matches. "
                    "Stop, verify or change the item, then Start again."
                )
                self._log.write(clip, "BLOCKED", f"startup: {reason}")
            else:
                if IS_WINDOWS and self._hwnd:
                    win32gui.EnableWindow(self._hwnd, True)
                self._status_var.set(f"Active — {reason}")
                self._log.write(clip, "allowed", f"startup: {reason}")
        else:
            if IS_WINDOWS and self._hwnd:
                win32gui.EnableWindow(self._hwnd, True)
            self._status_var.set("Active — no clipboard content")

        self._start_listener()
        self.root.after(POLL_MS, self._tick)

    def _stop(self) -> None:
        self._is_active     = False
        self._should_ctrl_c      = False  # discard any pending Ctrl+C before Stop
        self._ctrl_c_at          = None
        self._last_was_desirable = False
        self._stop_listener()
        if IS_WINDOWS and self._hwnd:
            try:
                win32gui.EnableWindow(self._hwnd, True)
            except Exception:
                pass
        if self._log:
            self._log.write("", "SESSION", "stop")
        self._hwnd  = None
        self._log   = None
        self._toggle_btn.config(text="Start")
        self._status_var.set("Stopped")

    def _on_close(self) -> None:
        if self._is_active:
            self._stop()
        self.root.destroy()

    # ── mouse listener ────────────────────────────────────────────────────────

    def _start_listener(self) -> None:
        hwnd = self._hwnd

        def on_click(x, y, button, pressed):
            if not pressed or button != mouse.Button.left or not self._is_active:
                return
            if not IS_WINDOWS or not hwnd or hwnd != self._hwnd:
                return
            try:
                lx, ty, rx, by = win32gui.GetWindowRect(hwnd)
            except Exception:
                return
            if not (lx <= x <= rx and ty <= y <= by):
                return
            # Click is inside the target window.
            if self._last_was_desirable:
                # WH_MOUSE_LL fires before DirectX, so suppress_event() prevents
                # PoE from ever seeing this click — stops stash from cycling past
                # the blocked item.
                if self._log:
                    self._log.write("", "SUPPRESSED", "click blocked at OS level")
                self._listener.suppress_event()
            else:
                if self._log:
                    self._log.write("", "CLICK", "click received — queuing Ctrl+C")
                self._should_ctrl_c = True

        self._listener = mouse.Listener(on_click=on_click, suppress=False)
        self._listener.start()

    def _stop_listener(self) -> None:
        if self._listener:
            self._listener.stop()
            self._listener.join(timeout=1.0)  # wait for thread to exit before next _start()
            self._listener = None

    # ── polling tick ──────────────────────────────────────────────────────────

    def _tick(self) -> None:
        if not self._is_active:
            return
        try:
            if self._should_ctrl_c:
                self._should_ctrl_c = False
                if self._log:
                    self._log.write("", "CTRL+C", "sending hotkey; disabling window")
                pyautogui.hotkey("ctrl", "c")
                # Disable immediately after Ctrl+C — window was enabled so Ctrl+C
                # reached PoE; now block spam clicks while we wait for evaluation.
                if IS_WINDOWS and self._hwnd:
                    try:
                        win32gui.EnableWindow(self._hwnd, False)
                        self._ctrl_c_at = time.monotonic()
                    except Exception:
                        pass
            try:
                text = self.root.clipboard_get()
            except tk.TclError:
                text = ""
            self._clipboard_var.set(text)
            if self._hwnd and text != self._last_clip:
                self._ctrl_c_at = None  # clipboard changed; no need to time out
                self._apply_result(text)
            elif self._ctrl_c_at is not None:
                # Clipboard unchanged 200 ms after Ctrl+C. Only re-enable if the
                # last evaluated item was NOT desirable — if it WAS desirable we
                # stay blocked; pynput suppress_event() keeps PoE from cycling.
                if time.monotonic() - self._ctrl_c_at > 0.200:
                    self._ctrl_c_at = None
                    if not self._last_was_desirable and IS_WINDOWS and self._hwnd:
                        try:
                            win32gui.EnableWindow(self._hwnd, True)
                            if self._log:
                                self._log.write("", "TIMEOUT", "clipboard unchanged 200ms — re-enabled")
                        except Exception:
                            pass
                    elif self._last_was_desirable and self._log:
                        self._log.write("", "TIMEOUT", "clipboard unchanged 200ms — staying blocked")
        except Exception as exc:
            self._status_var.set(f"Error: {exc}")
        self.root.after(POLL_MS, self._tick)  # always reschedule

    def _apply_result(self, text: str) -> None:
        desirable   = self._is_desirable(text)
        reason      = self._eval_reason(text)
        self._last_clip          = text
        self._last_was_desirable = desirable
        if IS_WINDOWS and self._hwnd:
            win32gui.EnableWindow(self._hwnd, not desirable)
        action = "BLOCKED" if desirable else "allowed"
        self._status_var.set(f"{'Blocked' if desirable else 'Allowed'} — {reason}")
        if self._log:
            self._log.write(text, action, reason)

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
