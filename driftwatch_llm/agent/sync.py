"""Delivers the agent's outbox to DriftWatch.

One round (`drain_once`) takes due events, looks up each project's key, validates the event against the
shared contract, and sends it through `Api.ingest_event`:

- accepted or duplicate  -> sent
- key rejected (PT401)   -> the project is parked, its events stay queued, nothing is lost
- no key stored          -> parked as `needs_login` until a key appears
- event refused (PT422)  -> quarantined (kept, never retried)
- anything else          -> rescheduled with backoff (and `Retry-After`), and the round stops, so a
                            struggling server is not hammered

Keys are read from the secret store per call and never logged, stored or put in status output.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Callable

from driftwatch_llm.agent.store import AgentStore
from driftwatch_llm.api import Api, AuthRejected, Rejected, TransientError
from driftwatch_llm.core.events import IngestionError, validate_event


def _fingerprint(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


class SyncWorker:
    def __init__(
        self,
        store: AgentStore,
        api: Api,
        secrets: Any,
        clock: Callable[[], float] = time.time,
        batch_size: int = 50,
    ) -> None:
        self._store = store
        self._api = api
        self._secrets = secrets
        self._clock = clock
        self._batch = batch_size
        self._rejected_fingerprints: dict[str, str] = {}
        self._sent_total = 0
        self._last_success_at: float | None = None
        self._last_error: str | None = None

    def _maybe_unpark(self) -> None:
        for project_id, reason in self._store.parked().items():
            found = self._secrets.load(project_id)
            if found is None:
                continue
            if reason == "needs_login":
                self._store.unpark_project(project_id)
            elif reason == "auth_failed":
                # A different key than the rejected one means the user logged in again. After a restart
                # there is no fingerprint, so one request tries the stored key again.
                if _fingerprint(found[0]) != self._rejected_fingerprints.get(project_id):
                    self._store.unpark_project(project_id)

    def drain_once(self) -> dict[str, int]:
        counts = {"sent": 0, "retry": 0, "quarantined": 0, "parked": 0, "no_key": 0, "invalid": 0}
        self._maybe_unpark()
        skip: set[str] = set()
        keys: dict[str, str] = {}
        for row in self._store.due(limit=self._batch):
            pid = row.project_id
            if pid in skip:
                continue
            key = keys.get(pid)
            if key is None:
                found = self._secrets.load(pid)
                if found is None:
                    self._store.park_project(pid, "needs_login")
                    counts["no_key"] += 1
                    skip.add(pid)
                    continue
                key = keys[pid] = found[0]
            try:
                validate_event(row.payload)
            except IngestionError:
                self._store.mark_failed(row.event_id, "failed the local event contract", permanent=True)
                self._store.bump("invalid_events")
                counts["invalid"] += 1
                continue
            try:
                self._api.ingest_event(key, row.payload)
            except AuthRejected as exc:
                self._store.park_project(pid, "auth_failed")
                self._rejected_fingerprints[pid] = _fingerprint(key)
                self._last_error = str(exc)
                counts["parked"] += 1
                skip.add(pid)
            except Rejected as exc:
                self._store.mark_failed(row.event_id, str(exc), permanent=True)
                self._last_error = str(exc)
                counts["quarantined"] += 1
            except TransientError as exc:
                self._store.mark_failed(row.event_id, str(exc), permanent=False, retry_after=exc.retry_after)
                self._last_error = str(exc)
                counts["retry"] += 1
                break
            else:
                self._store.mark_sent(row.event_id)
                self._sent_total += 1
                self._last_success_at = self._clock()
                counts["sent"] += 1
        return counts

    def status(self) -> dict[str, Any]:
        counts = self._store.counts()
        return {
            "sent_total": self._sent_total,
            "last_success_at": self._last_success_at,
            "last_error": self._last_error,
            "pending": counts["pending"],
            "quarantined": counts["quarantined"],
            "parked": self._store.parked(),
            "dropped_total": self._store.counter("dropped_total"),
        }
