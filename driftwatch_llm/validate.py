"""Tiny shared validators."""

from __future__ import annotations

import re

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


def is_uuid(value: object) -> bool:
    return isinstance(value, str) and _UUID_RE.match(value) is not None
