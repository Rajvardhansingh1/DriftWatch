"""Thin repository interface over signal persistence (Spec_Upgrade.md
Phase 1: "introduce adapters/interfaces around existing functions instead
of rewriting algorithms without need"). Signal analyzers depend on this
Protocol, not directly on SQLAlchemy — so Phase 2+'s dual local/cloud
persistence can add a second implementation without touching any signal
analyzer. LocalSQLiteRepository is the only implementation today; it
simply delegates to the existing write_signal/read_signal_window
functions, unchanged."""
from __future__ import annotations

from datetime import datetime
from typing import Protocol

from sqlalchemy.orm import Session

from monitor.db.models import SignalRecord
from monitor.db.writer import read_signal_window, write_signal


class SignalRepository(Protocol):
    def write_signal(
        self,
        signal: str,
        value: float,
        meta: dict | None = None,
        timestamp: datetime | None = None,
    ) -> SignalRecord: ...

    def read_signal_window(self, signal: str, limit: int = 100) -> list[SignalRecord]: ...


class LocalSQLiteRepository:
    """Default SignalRepository backed by the existing local SQLite
    writer/reader. Bound to a single Session for its lifetime, matching
    how call sites already obtain a session today."""

    def __init__(self, session: Session):
        self._session = session

    def write_signal(
        self,
        signal: str,
        value: float,
        meta: dict | None = None,
        timestamp: datetime | None = None,
    ) -> SignalRecord:
        return write_signal(self._session, signal, value, meta=meta, timestamp=timestamp)

    def read_signal_window(self, signal: str, limit: int = 100) -> list[SignalRecord]:
        return read_signal_window(self._session, signal, limit=limit)
