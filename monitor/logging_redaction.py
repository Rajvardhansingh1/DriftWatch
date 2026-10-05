"""Redacts secret-shaped strings from log records before they are emitted
(Spec_Upgrade.md section 13.1). Defense in depth: code should never log
secrets in the first place; this catches the ones that slip through
(exception messages, echoed headers, provider error bodies)."""
from __future__ import annotations

import logging
import re

_PATTERNS = [
    (re.compile(r"Bearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE), "Bearer [REDACTED]"),
    (re.compile(r"eyJ[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}"), "[REDACTED_JWT]"),
    (re.compile(r"gsk_[A-Za-z0-9]{10,}"), "[REDACTED_GROQ_KEY]"),
    (re.compile(r"AIza[0-9A-Za-z_\-]{20,}"), "[REDACTED_GOOGLE_KEY]"),
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "[REDACTED_KEY]"),
    (re.compile(r"postgres(?:ql)?://[^\s:@]+:[^\s@]+@"), "postgresql://[REDACTED]@"),
]


def redact(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(str(record.getMessage()))
        record.args = ()
        return True


_installed = False


def install() -> None:
    """Redacts every record at creation, so it holds even when uvicorn or
    a library attaches its own handlers after startup. Idempotent."""
    global _installed
    if _installed:
        return
    previous = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        record.msg = redact(record.getMessage())
        record.args = ()
        return record

    logging.setLogRecordFactory(factory)
    _installed = True
