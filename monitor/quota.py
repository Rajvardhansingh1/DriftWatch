"""Live API-call budget for the quota badge (spec §3/§10) — an honest
'API calls: x/y used today' indicator so the demo never silently degrades."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class QuotaTracker:
    limit: int
    used: int = 0

    def increment(self, n: int = 1) -> None:
        self.used += n

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    @property
    def exceeded(self) -> bool:
        return self.used >= self.limit

    def reset(self) -> None:
        self.used = 0
