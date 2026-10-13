"""Known-answer matching for canary probes. Standard library only (shared by the server's demo, the runner and tests)."""
from __future__ import annotations

import difflib


def score_answer(actual: str, expected: str, match_type: str = "contains") -> bool:
    actual_n = actual.strip().lower()
    expected_n = expected.strip().lower()
    if match_type == "exact":
        return actual_n == expected_n
    if match_type == "contains":
        return expected_n in actual_n
    if match_type == "fuzzy":
        return difflib.SequenceMatcher(None, actual_n, expected_n).ratio() >= 0.6
    raise ValueError(f"unknown match_type: {match_type}")
