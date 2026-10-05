from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from monitor.db.models import SignalRecord

# Bumped only if the meaning/shape of a signal row's meta changes in a way
# a reader (dashboard, cloud sync, migration script) must handle
# differently. Per Spec_Upgrade.md §9.2/§7.4 - every persisted signal
# result carries its schema version so future consumers don't have to
# guess which shape an older row used.
SIGNAL_META_SCHEMA_VERSION = 1


def write_signal(
    session: Session,
    signal: str,
    value: float,
    meta: dict | None = None,
    timestamp: datetime | None = None,
) -> SignalRecord:
    full_meta = {"schema_version": SIGNAL_META_SCHEMA_VERSION, **(meta or {})}
    record = SignalRecord(
        signal=signal,
        value=value,
        meta=json.dumps(full_meta),
        timestamp=timestamp or datetime.now(timezone.utc),
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def read_signal_window(session: Session, signal: str, limit: int = 100) -> list[SignalRecord]:
    stmt = (
        select(SignalRecord)
        .where(SignalRecord.signal == signal)
        .order_by(SignalRecord.timestamp.desc(), SignalRecord.id.desc())
        .limit(limit)
    )
    return list(session.execute(stmt).scalars().all())
