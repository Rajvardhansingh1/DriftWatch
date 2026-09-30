"""Shared in-process rate limiter for the demo bot's live LLM calls and
the judge's rubric-scoring calls — the "same rate-limited path" the spec
requires. Per-session HTTP rate limiting (slowapi) wraps the API layer
around this in Phase 6/8; this is the call-level enforcement underneath it."""
from __future__ import annotations

import time
from dataclasses import dataclass, field


class RateLimitExceeded(Exception):
    pass


@dataclass
class SharedRateLimiter:
    max_calls: int
    period_seconds: float = 60.0
    _timestamps: list[float] = field(default_factory=list)

    def consume(self) -> None:
        now = time.monotonic()
        self._timestamps = [t for t in self._timestamps if now - t < self.period_seconds]
        if len(self._timestamps) >= self.max_calls:
            raise RateLimitExceeded(
                f"rate limit exceeded: {self.max_calls} calls per {self.period_seconds}s"
            )
        self._timestamps.append(now)
