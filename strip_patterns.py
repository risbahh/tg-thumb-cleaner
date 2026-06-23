"""
strip_patterns.py — Runtime-editable caption watermark patterns for tg-thumb-cleaner.

Patterns are stored in strip_patterns.json and loaded dynamically on every
caption clean — no restart needed after add/remove.

Built-in patterns in caption_cleaner.py always run too; these are additive.
"""
import json
import os
import re
import threading

_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "strip_patterns.json")
_lock = threading.Lock()


def load() -> list[str]:
    """Return list of raw regex strings from strip_patterns.json."""
    try:
        with _lock:
            with open(_FILE) as f:
                return [p for p in json.load(f) if p]
    except Exception:
        return []


def _save(patterns: list[str]):
    with _lock:
        with open(_FILE, "w") as f:
            json.dump(patterns, f, indent=2)


def add(pattern: str) -> str:
    """Validate and add a regex pattern. Returns error string or empty string on success."""
    try:
        re.compile(pattern)
    except re.error as e:
        return f"Invalid regex: {e}"
    current = load()
    if pattern in current:
        return "Pattern already exists."
    current.append(pattern)
    _save(current)
    return ""


def remove(index: int) -> str:
    """Remove pattern by 1-based index. Returns error string or empty string on success."""
    current = load()
    if not current:
        return "No custom patterns to remove."
    if index < 1 or index > len(current):
        return f"Index out of range — use 1 to {len(current)}."
    removed = current.pop(index - 1)
    _save(current)
    return ""


def count() -> int:
    return len(load())
