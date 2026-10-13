"""Masks secrets and personal data before anything is sent off the machine for grading. Standard library only.

This is a safety net with a clear scope, not a promise to find every secret: it catches the shapes that leak most
often (API keys and tokens, bearer headers, JWTs, credentials inside URLs, e-mail addresses, long digit runs such as
card and phone numbers, SSN-like numbers, long random-looking tokens). Free text can still contain things only a human
would recognise, which is one reason grading is opt-in and sampled.
"""
from __future__ import annotations

import re

MAX_CHARS = 1500  # what one judged response is cut to, after masking
_PRE_CUT = MAX_CHARS * 4  # bound the work on huge texts; cut at a word so no half-secret remains at the edge

_SECRET = "[secret]"
_RULES: list[tuple[re.Pattern[str], str]] = [
    # credentials inside a URL: scheme://user:password@host
    (re.compile(r"\b([a-z][a-z0-9+.\-]*://)[^\s/:@]+:[^\s/@]+@", re.IGNORECASE), r"\1" + _SECRET + "@"),
    (re.compile(r"\bBearer\s+[A-Za-z0-9._~+/\-]{8,}=*", re.IGNORECASE), "Bearer " + _SECRET),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}"), _SECRET),
    (re.compile(r"\b(?:sk-|gsk_|ghp_|gho_|ghs_|ghu_|xox[abprs]-)[A-Za-z0-9_\-]{12,}"), _SECRET),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{20,}"), _SECRET),
    (re.compile(r"\bdw_[0-9a-f]{10}_[0-9a-f]{64}\b"), _SECRET),
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), _SECRET),
]
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
_LONG_TOKEN = re.compile(r"\b(?=[A-Za-z0-9_\-]*[A-Za-z])(?=[A-Za-z0-9_\-]*\d)[A-Za-z0-9_\-]{32,}\b")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_DIGIT_RUN = re.compile(r"(?<![\w$#.])\+?\(?\d[\d\s().\-]{6,}\d(?![\w])")


def _mask_number(match: re.Match[str]) -> str:
    digits = sum(ch.isdigit() for ch in match.group(0))
    return "[number]" if digits >= 9 else match.group(0)  # dates, prices and counts are shorter than that


def redact(text: str) -> str:
    for pattern, replacement in _RULES:
        text = pattern.sub(replacement, text)
    text = _EMAIL.sub("[email]", text)
    text = _LONG_TOKEN.sub(_SECRET, text)
    text = _SSN.sub("[number]", text)
    return _DIGIT_RUN.sub(_mask_number, text)


def prepare_for_judge(text: object) -> str:
    """What a judged response is reduced to: masked first, then cut. Anything that is not text becomes ''."""
    if not isinstance(text, str) or not text.strip():
        return ""
    if len(text) > _PRE_CUT:
        head = text[:_PRE_CUT]
        text = head.rsplit(None, 1)[0] if re.search(r"\s", head) else head
    return redact(text).strip()[:MAX_CHARS]
