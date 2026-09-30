from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


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
