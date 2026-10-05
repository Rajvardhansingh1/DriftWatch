"""Drains the local outbox to the cloud (Spec_Upgrade.md 8.2). The sender is
injected so the same loop runs against the real ingestion endpoint or a
test double. The sender raises TransientSyncError (retry later) or
PermanentSyncError (quarantine, never retry, never delete)."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Callable

from sqlalchemy.orm import Session

from monitor.db.models import SyncOutbox
from monitor.sync.outbox import due, mark_failed, mark_sent


class TransientSyncError(Exception):
    """Network down, timeout, 5xx, 429. Safe to retry the same event."""


class PermanentSyncError(Exception):
    """Validation or authorization rejected the event. Retrying cannot help."""


Sender = Callable[[dict], None]


def drain(
    session: Session,
    sender: Sender,
    now: datetime | None = None,
    batch_size: int = 100,
) -> dict[str, int]:
    counts = {"sent": 0, "retry": 0, "quarantined": 0}
    for row in due(session, now=now, limit=batch_size):
        event = json.loads(row.payload)
        try:
            sender(event)
        except TransientSyncError as exc:
            mark_failed(session, row, str(exc), permanent=False, now=now)
            counts["retry"] += 1
        except PermanentSyncError as exc:
            mark_failed(session, row, str(exc), permanent=True, now=now)
            counts["quarantined"] += 1
        else:
            mark_sent(session, row)
            counts["sent"] += 1
    return counts


def pending_count(session: Session) -> int:
    from sqlalchemy import func, select

    return session.execute(
        select(func.count()).select_from(SyncOutbox).where(SyncOutbox.status == "pending")
    ).scalar_one()
