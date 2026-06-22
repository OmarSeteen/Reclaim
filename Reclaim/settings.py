"""Persisted UI settings and a human-readable cleanup history.

Pure JSON/text I/O over the two files named in config — no GUI, no shell. Every
operation is best-effort: a missing or corrupt settings file must never stop the
app starting, so reads fall back to empty and writes swallow I/O errors. The GUI
is the only caller; keeping this separate means "what do we remember between
runs" is answerable in one small place.
"""

import json
import os
import time

from . import config


def _ensure_dir():
    """Create the app-data folder if needed. Silent on failure (we degrade to
    not-persisting rather than crashing)."""
    try:
        os.makedirs(config.APP_DATA_DIR, exist_ok=True)
    except OSError:
        pass


def load():
    """Return the saved settings dict, or {} when there's nothing valid yet.

    A corrupt file (hand-edited, truncated by a crash) is treated as absent
    rather than fatal — the user just gets defaults, which is always safe.
    """
    try:
        with open(config.SETTINGS_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(data):
    """Write settings as pretty JSON. Best-effort; a failed write just means the
    next run starts from defaults.

    Written to a temp file and atomically swapped in with os.replace: opening the
    real file in "w" would truncate it *first*, so a serialization error or a
    crash/power-loss mid-write would leave corrupt JSON and silently wipe every
    persisted setting (theme, language, and the custom/excluded dir lists) on the
    next launch. The swap means the live file is only ever a complete document.
    """
    _ensure_dir()
    tmp = config.SETTINGS_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, config.SETTINGS_FILE)
    except (OSError, TypeError):
        try:
            os.remove(tmp)        # don't leave a half-written temp behind
        except OSError:
            pass


def record_cleanup(summary):
    """Add one timestamped line describing a run to the history log.

    Plain text on purpose: the history is meant to be readable in any editor.
    We rewrite the file keeping only the most recent HISTORY_MAX_LINES so this
    append-only log stays bounded — a tool that exists to stop junk piling up
    shouldn't grow an unbounded log of its own. The file is tiny (one short line
    per run), so rewriting it each time is cheaper than it sounds.
    """
    _ensure_dir()
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {summary}\n"
    try:
        try:
            with open(config.HISTORY_FILE, "r", encoding="utf-8") as fh:
                lines = fh.readlines()
        except OSError:
            lines = []
        lines.append(line)
        if len(lines) > config.HISTORY_MAX_LINES:
            lines = lines[-config.HISTORY_MAX_LINES:]
        with open(config.HISTORY_FILE, "w", encoding="utf-8") as fh:
            fh.writelines(lines)
    except OSError:
        pass


def clear_history():
    """Delete the cleanup-history log. Best-effort; absence is success."""
    try:
        if os.path.exists(config.HISTORY_FILE):
            os.remove(config.HISTORY_FILE)
    except OSError:
        pass


def history_text(limit=None):
    """Return the last `limit` history lines as one string for display."""
    if limit is None:
        limit = config.HISTORY_VIEW_LINES
    try:
        with open(config.HISTORY_FILE, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
        return "".join(lines[-limit:]) or "No cleanup history yet."
    except OSError:
        return "No cleanup history yet."
