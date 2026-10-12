"""The agent's local store: signal history, the sync outbox, parked projects, counters and baselines.

Standard-library SQLite (numpy is imported only to read or write a baseline). Invariants:

- `enqueue` is idempotent on event_id.
- A failed event is rescheduled with the shared backoff (and any server `Retry-After`); a permanent
  failure or too many attempts moves it to `quarantined`. Nothing is deleted except by the pending
  cap (counted in `dropped_total`) and by retention in `prune`.
- A parked project (for example after a 401) is skipped by `due()`; its events stay queued.
- Raw text is never stored: baselines are embedding vectors only.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from driftwatch_llm.core.backoff import MAX_ATTEMPTS, backoff_seconds

SIGNAL_RETENTION_SECONDS = 30 * 86400
SENT_RETENTION_SECONDS = 86400
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)

_SCHEMA = """
create table if not exists signals (
  id integer primary key autoincrement,
  project_id text not null,
  ts real not null,
  signal text not null,
  value real not null,
  meta text not null default '{}'
);
create index if not exists signals_lookup on signals (project_id, signal, ts);
create table if not exists outbox (
  event_id text primary key,
  project_id text not null,
  payload text not null,
  status text not null default 'pending',
  attempts integer not null default 0,
  next_attempt_at real not null,
  last_error text,
  created_at real not null,
  sent_at real
);
create index if not exists outbox_due on outbox (status, next_attempt_at);
create table if not exists parked (
  project_id text primary key,
  reason text not null,
  since real not null
);
create table if not exists counters (
  name text primary key,
  value integer not null default 0
);
"""


@dataclass(frozen=True)
class OutboxRow:
    event_id: str
    project_id: str
    payload: dict[str, Any]
    attempts: int


class AgentStore:
    def __init__(
        self,
        path: Path | str,
        max_pending: int = 5000,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._baselines = self._path.parent / "baselines"
        self._max_pending = max_pending
        self._clock = clock
        self._lock = threading.RLock()
        self._con = sqlite3.connect(str(self._path), check_same_thread=False, timeout=10, isolation_level=None)
        self._con.row_factory = sqlite3.Row
        with self._lock:
            self._con.execute("pragma journal_mode = wal")
            self._con.execute("pragma synchronous = normal")
            self._con.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._con.close()

    # -- signals ------------------------------------------------------------------------
    def add_signal(self, project_id: str, signal: str, value: float, meta: dict | None = None, ts: float | None = None) -> None:
        with self._lock:
            self._con.execute(
                "insert into signals (project_id, ts, signal, value, meta) values (?, ?, ?, ?, ?)",
                (project_id, self._clock() if ts is None else ts, signal, float(value), json.dumps(meta or {})),
            )

    def recent_signals(self, project_id: str, signal: str, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._con.execute(
                "select ts, value, meta from signals where project_id = ? and signal = ? "
                "order by ts desc, id desc limit ?",
                (project_id, signal, limit),
            ).fetchall()
        return [{"ts": r["ts"], "value": r["value"], "meta": json.loads(r["meta"])} for r in rows]

    # -- outbox -------------------------------------------------------------------------
    def enqueue(self, project_id: str, event: dict[str, Any]) -> bool:
        now = self._clock()
        with self._lock:
            cur = self._con.execute(
                "insert or ignore into outbox (event_id, project_id, payload, next_attempt_at, created_at) "
                "values (?, ?, ?, ?, ?)",
                (event["event_id"], project_id, json.dumps(event), now, now),
            )
            added = cur.rowcount == 1
            if added:
                self._enforce_cap()
        return added

    def _enforce_cap(self) -> None:
        pending = self._con.execute("select count(*) from outbox where status = 'pending'").fetchone()[0]
        excess = pending - self._max_pending
        if excess > 0:
            self._con.execute(
                "delete from outbox where event_id in (select event_id from outbox where status = 'pending' "
                "order by created_at, rowid limit ?)",
                (excess,),
            )
            self.bump("dropped_total", excess)

    def due(self, now: float | None = None, limit: int = 100) -> list[OutboxRow]:
        now = self._clock() if now is None else now
        with self._lock:
            rows = self._con.execute(
                "select event_id, project_id, payload, attempts from outbox "
                "where status = 'pending' and next_attempt_at <= ? "
                "and project_id not in (select project_id from parked) "
                "order by next_attempt_at, rowid limit ?",
                (now, limit),
            ).fetchall()
        return [OutboxRow(r["event_id"], r["project_id"], json.loads(r["payload"]), r["attempts"]) for r in rows]

    def mark_sent(self, event_id: str) -> None:
        with self._lock:
            self._con.execute(
                "update outbox set status = 'sent', sent_at = ?, last_error = null where event_id = ?",
                (self._clock(), event_id),
            )

    def mark_failed(self, event_id: str, error: str, permanent: bool, retry_after: float | None = None) -> None:
        now = self._clock()
        with self._lock:
            row = self._con.execute("select attempts from outbox where event_id = ?", (event_id,)).fetchone()
            if row is None:
                return
            attempts = row["attempts"] + 1
            if permanent or attempts >= MAX_ATTEMPTS:
                self._con.execute(
                    "update outbox set status = 'quarantined', attempts = ?, last_error = ? where event_id = ?",
                    (attempts, error[:300], event_id),
                )
                return
            delay = max(backoff_seconds(attempts), retry_after or 0.0)
            self._con.execute(
                "update outbox set attempts = ?, last_error = ?, next_attempt_at = ? where event_id = ?",
                (attempts, error[:300], now + delay, event_id),
            )

    def pending_count(self, project_id: str | None = None) -> int:
        sql = "select count(*) from outbox where status = 'pending'"
        args: tuple = ()
        if project_id is not None:
            sql += " and project_id = ?"
            args = (project_id,)
        with self._lock:
            return int(self._con.execute(sql, args).fetchone()[0])

    def counts(self) -> dict[str, int]:
        out = {"pending": 0, "sent": 0, "quarantined": 0}
        with self._lock:
            for status, n in self._con.execute("select status, count(*) from outbox group by status"):
                out[status] = int(n)
        return out

    # -- parked projects ----------------------------------------------------------------
    def park_project(self, project_id: str, reason: str) -> None:
        with self._lock:
            self._con.execute(
                "insert or replace into parked (project_id, reason, since) values (?, ?, ?)",
                (project_id, reason[:100], self._clock()),
            )

    def unpark_project(self, project_id: str) -> None:
        with self._lock:
            self._con.execute("delete from parked where project_id = ?", (project_id,))

    def parked(self) -> dict[str, str]:
        with self._lock:
            return {r["project_id"]: r["reason"] for r in self._con.execute("select project_id, reason from parked")}

    # -- counters -----------------------------------------------------------------------
    def bump(self, name: str, n: int = 1) -> None:
        with self._lock:
            self._con.execute(
                "insert into counters (name, value) values (?, ?) "
                "on conflict (name) do update set value = value + excluded.value",
                (name, n),
            )

    def counter(self, name: str) -> int:
        with self._lock:
            row = self._con.execute("select value from counters where name = ?", (name,)).fetchone()
        return int(row["value"]) if row else 0

    def counters(self) -> dict[str, int]:
        with self._lock:
            return {r["name"]: int(r["value"]) for r in self._con.execute("select name, value from counters")}

    # -- baselines (vectors only) -------------------------------------------------------
    def _baseline_path(self, project_id: str) -> Path:
        if not _UUID_RE.match(project_id):
            raise ValueError("invalid project id")
        return self._baselines / f"{project_id.lower()}.npz"

    def save_baseline(self, project_id: str, vectors: Any) -> None:
        import numpy as np

        path = self._baseline_path(project_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".tmp-{os.getpid()}-{path.name}")
        np.savez(tmp, vectors=np.asarray(vectors, dtype=np.float32))
        os.replace(tmp, path)

    def load_baseline(self, project_id: str) -> Any | None:
        import numpy as np

        path = self._baseline_path(project_id)
        if not path.is_file():
            return None
        try:
            with np.load(path, allow_pickle=False) as z:
                return z["vectors"].astype(np.float32)
        except Exception:  # noqa: BLE001 - a damaged baseline is rebuilt, never fatal
            return None

    def clear_baseline(self, project_id: str) -> None:
        try:
            self._baseline_path(project_id).unlink()
        except FileNotFoundError:
            pass

    # -- retention ----------------------------------------------------------------------
    def prune(self) -> None:
        now = self._clock()
        with self._lock:
            self._con.execute("delete from signals where ts < ?", (now - SIGNAL_RETENTION_SECONDS,))
            self._con.execute(
                "delete from outbox where status = 'sent' and sent_at < ?", (now - SENT_RETENTION_SECONDS,)
            )
