"""
seen_db.py — Deduplication for tg-thumb-cleaner.

Stores file_unique_id values in memory + seen.json on disk.
Telegram's file_unique_id is a globally unique fingerprint per file —
the same video posted in two groups has the same file_unique_id.

Thread-safe (file lock). Survives restarts.
"""
import json
import os
import threading

_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seen.json")
_lock = threading.Lock()
_seen: set[str] = set()
_loaded = False


def _load():
    global _seen, _loaded
    if _loaded:
        return
    try:
        with open(_FILE) as f:
            _seen = set(json.load(f))
    except Exception:
        _seen = set()
    _loaded = True


def is_seen(uid: str) -> bool:
    with _lock:
        _load()
        return uid in _seen


def mark_seen(uid: str):
    with _lock:
        _load()
        _seen.add(uid)
        try:
            with open(_FILE, "w") as f:
                json.dump(list(_seen), f)
        except Exception:
            pass


def count() -> int:
    with _lock:
        _load()
        return len(_seen)


def reset():
    global _seen
    with _lock:
        _seen = set()
        try:
            with open(_FILE, "w") as f:
                json.dump([], f)
        except Exception:
            pass


def get_unique_id(message) -> str | None:
    """Extract file_unique_id from a video or document message."""
    for attr in ("video", "document", "audio", "photo"):
        obj = getattr(message, attr, None)
        if obj:
            uid = getattr(obj, "file_unique_id", None)
            if uid:
                return uid
    return None
