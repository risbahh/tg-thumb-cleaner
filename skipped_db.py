"""
skipped_db.py — Tracks the last 50 files skipped as duplicates.

Used by /listskipped to show what was skipped with filename + time.
In-memory only (resets on restart) — not persisted to disk.
"""
import time
from collections import deque
from typing import Optional

_MAX = 50
_skipped: deque = deque(maxlen=_MAX)
_total_session = 0


def record(filename: Optional[str], uid: str):
    global _total_session
    _skipped.append({
        "filename": filename or "unknown",
        "uid": uid[:12] + "…" if uid else "?",
        "ts": time.time(),
    })
    _total_session += 1


def list_recent() -> list:
    """Return entries newest-first."""
    return list(reversed(_skipped))


def session_count() -> int:
    return _total_session
