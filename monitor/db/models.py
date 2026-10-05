from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SyncOutbox(Base):
    """Locally committed events awaiting cloud sync (Spec_Upgrade.md 8.2).
    Rows are never deleted by the sync worker - they move pending -> sent,
    or pending -> quarantined on a permanent error, so a failed sync can't
    silently lose a record."""

    __tablename__ = "sync_outbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    payload: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, index=True, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class SignalRecord(Base):
    """One row per signal observation. All five signals (embedding_drift,
    self_consistency, canary_accuracy, judge_trend, hallucination_score)
    and the combined score share this table, keyed by timestamp."""

    __tablename__ = "signal_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )
    signal: Mapped[str] = mapped_column(String, index=True)
    value: Mapped[float] = mapped_column(Float)
    meta: Mapped[str | None] = mapped_column(Text, nullable=True)
