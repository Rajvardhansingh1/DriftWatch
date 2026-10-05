"""Local sync outbox (Spec_Upgrade.md section 8.2). Locally committed events
are queued here and drained to the cloud by a worker. Invariants:

- enqueue is idempotent on event_id (a retried local write never queues twice).
- transient failures reschedule with bounded exponential backoff + jitter.
- permanent failures move the row to 'quarantined' - kept, never deleted.
- nothing is removed from the outbox by this module, so offline operation
  never silently drops records.
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from monitor.db.models import SyncOutbox

BASE_DELAY_SECONDS = 5
MAX_DELAY_SECONDS = 15 * 60
MAX_ATTEMPTS = 20


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def enqueue(session: Session, event: dict, now: datetime | None = None) -> bool:
    """Returns True if newly queued, False if this event_id is already in the outbox."""
    row = SyncOutbox(
        event_id=event["event_id"],
        payload=json.dumps(event),
        status="pending",
        attempts=0,
        next_attempt_at=now or _utcnow(),
    )
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        return False
    return True


def due(session: Session, now: datetime | None = None, limit: int = 100) -> list[SyncOutbox]:
    stmt = (
        select(SyncOutbox)
        .where(SyncOutbox.status == "pending", SyncOutbox.next_attempt_at <= (now or _utcnow()))
        .order_by(SyncOutbox.next_attempt_at, SyncOutbox.id)
        .limit(limit)
    )
    return list(session.execute(stmt).scalars().all())


def mark_sent(session: Session, row: SyncOutbox) -> None:
    row.status = "sent"
    row.last_error = None
    session.commit()


def backoff_seconds(attempts: int, rng: Callable[[], float] = random.random) -> float:
    """Bounded exponential backoff with full jitter on the upper half."""
    capped = min(MAX_DELAY_SECONDS, BASE_DELAY_SECONDS * (2 ** attempts))
    return capped * (0.5 + 0.5 * rng())


def mark_failed(
    session: Session,
    row: SyncOutbox,
    error: str,
    permanent: bool,
    now: datetime | None = None,
    rng: Callable[[], float] = random.random,
) -> None:
    row.attempts += 1
    row.last_error = error[:500]
    if permanent or row.attempts >= MAX_ATTEMPTS:
        row.status = "quarantined"
    else:
        row.next_attempt_at = (now or _utcnow()) + timedelta(seconds=backoff_seconds(row.attempts, rng))
    session.commit()
