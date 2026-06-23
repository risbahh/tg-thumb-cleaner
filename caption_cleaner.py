"""
Strips watermarks and promo text from captions.
Handles @mentions, t.me links, URLs, [tags], and promo lines.

Built-in patterns run always.
Custom patterns are loaded dynamically from strip_patterns.json
via strip_patterns.load() — no restart needed after changes.
"""
import json
import os
import re

_BUILTIN = [
    re.compile(r'\[https?://[^\]]+\]'),
    re.compile(r'https?://\S+', re.I),
    re.compile(r't\.me/\S+', re.I),
    re.compile(r'@[A-Za-z0-9_]{3,}'),
    re.compile(r'\[[A-Za-z0-9._\-\s]{3,40}\]'),
    re.compile(r'^(Powered|Source|Join|Follow|Provided|Shared|Posted)\s*(by|:)[^\n]*', re.I | re.M),
    re.compile(r'^(For\s+more|More\s+movies|Visit\s+us)[^\n]*', re.I | re.M),
    re.compile(r'^\s*[-—•|]+\s*$', re.M),
]


def _custom_patterns() -> list:
    """Load and compile custom patterns from strip_patterns.json (dynamic, no restart)."""
    try:
        import strip_patterns
        return [re.compile(p, re.I | re.M) for p in strip_patterns.load() if p]
    except Exception:
        return []


def clean(caption: str | None) -> str | None:
    if not caption:
        return None
    result = caption
    for p in _BUILTIN:
        result = p.sub("", result)
    for p in _custom_patterns():
        result = p.sub("", result)
    result = re.sub(r'\n{3,}', '\n\n', result)
    result = result.strip()
    return result if result else None
