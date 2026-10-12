"""Retry backoff shared by the server outbox and the agent outbox."""
from __future__ import annotations

import random
from typing import Callable

BASE_DELAY_SECONDS = 5
MAX_DELAY_SECONDS = 15 * 60
MAX_ATTEMPTS = 20


def backoff_seconds(attempts: int, rng: Callable[[], float] = random.random) -> float:
    """Bounded exponential backoff with full jitter on the upper half."""
    capped = min(MAX_DELAY_SECONDS, BASE_DELAY_SECONDS * (2 ** attempts))
    return capped * (0.5 + 0.5 * rng())
