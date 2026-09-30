from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from monitor.db.models import SignalRecord


def write_signal(
    session: Session,
    signal: str,
    value: float,
    meta: dict | None = None,
    timestamp: datetime | None = None,
) -> SignalRecord:
    record = SignalRecord(
        signal=signal,
        value=value,
        meta=json.dumps(meta) if meta else None,
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
