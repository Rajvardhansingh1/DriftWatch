"""Tiny shared validators."""

from __future__ import annotations

import re

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]+")


def is_uuid(value: object) -> bool:
    return isinstance(value, str) and _UUID_RE.match(value) is not None


def clean_text(value: object, limit: int = 64) -> str:
    """Make server- or device-supplied text safe to print: no control characters (so no terminal
    escape sequences), single spaces, at most `limit` characters."""
    if not isinstance(value, str):
        return ""
    return " ".join(_CONTROL_RE.sub(" ", value).split())[:limit]
