"""Ingestion contract enforcement for the cloud data plane (Spec_Upgrade.md
sections 7.1, 7.2, 10.1). Validates an incoming event envelope against
schemas/event.v1.json and enforces idempotency: a duplicate event_id for
the same project is accepted once and reported as a duplicate afterward,
so retries never double-count signals or usage.

Validation is hand-written rather than pulling in a JSON Schema library -
the envelope is small and fixed, and the schema file remains the
published contract for external implementers."""
from __future__ import annotations

import json
import math
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

ALLOWED_SIGNALS = frozenset(
    {
        "embedding_drift",
        "self_consistency",
        "canary_accuracy",
        "judge_trend",
        "hallucination_score",
        "combined_score",
    }
)
REQUIRED_FIELDS = frozenset({"schema_version", "event_id", "occurred_at", "source", "signal", "value"})
OPTIONAL_STRING_FIELDS = frozenset(
    {"organization_id", "project_id", "environment", "runtime_id", "model_provider", "model_name", "request_id", "received_at"}
)
ALLOWED_FIELDS = REQUIRED_FIELDS | OPTIONAL_STRING_FIELDS | frozenset({"meta", "content_capture"})
MAX_META_BYTES = 4096
MAX_SOURCE_LEN = 128


class IngestionError(ValueError):
    """Client-side contract violation. Maps to HTTP 400/422 at the API
    boundary - never a 500, never an echo of internal detail."""


@dataclass(frozen=True)
class ValidatedEvent:
    event_id: str
    occurred_at: datetime
    source: str
    signal: str
    value: float
    meta: dict
    content_capture: bool


def validate_event(payload: dict) -> ValidatedEvent:
    if not isinstance(payload, dict):
        raise IngestionError("event must be a JSON object")

    unknown = set(payload) - ALLOWED_FIELDS
    if unknown:
        raise IngestionError(f"unknown field(s): {sorted(unknown)}")

    missing = REQUIRED_FIELDS - set(payload)
    if missing:
        raise IngestionError(f"missing required field(s): {sorted(missing)}")

    if payload["schema_version"] != 1:
        raise IngestionError("unsupported schema_version")

    try:
        event_id = str(uuid.UUID(str(payload["event_id"])))
    except ValueError as exc:
        raise IngestionError("event_id must be a UUID") from exc

    try:
        occurred_at = datetime.fromisoformat(str(payload["occurred_at"]))
    except ValueError as exc:
        raise IngestionError("occurred_at must be an ISO-8601 timestamp") from exc
    if occurred_at.tzinfo is None:
        raise IngestionError("occurred_at must include a timezone offset")

    signal = payload["signal"]
    if signal not in ALLOWED_SIGNALS:
        raise IngestionError("unknown signal")

    value = payload["value"]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise IngestionError("value must be a finite number")

    source = payload["source"]
    if not isinstance(source, str) or not source or len(source) > MAX_SOURCE_LEN:
        raise IngestionError("source must be a non-empty string up to 128 characters")

    meta = payload.get("meta", {})
    if not isinstance(meta, dict):
        raise IngestionError("meta must be an object")
    if len(json.dumps(meta)) > MAX_META_BYTES:
        raise IngestionError("meta exceeds size limit")

    content_capture = payload.get("content_capture", False)
    if not isinstance(content_capture, bool):
        raise IngestionError("content_capture must be a boolean")

    return ValidatedEvent(
        event_id=event_id,
        occurred_at=occurred_at,
        source=source,
        signal=signal,
        value=float(value),
        meta=meta,
        content_capture=content_capture,
    )


class IdempotencyStore(Protocol):
    def claim(self, project_id: str, event_id: str) -> bool:
        """Returns True if this (project_id, event_id) is new and now
        claimed; False if it was already seen (a duplicate delivery)."""
        ...


class InMemoryIdempotencyStore:
    """Test/offline implementation. The cloud implementation must make
    claim() a single atomic insert-if-absent (unique constraint on
    (project_id, event_id)) - a check-then-insert in application code
    would race across instances."""

    def __init__(self) -> None:
        self._seen: set[tuple[str, str]] = set()

    def claim(self, project_id: str, event_id: str) -> bool:
        key = (project_id, event_id)
        if key in self._seen:
            return False
        self._seen.add(key)
        return True


def ingest_event(payload: dict, project_id: str, store: IdempotencyStore) -> str:
    """Returns 'accepted' for a new event, 'duplicate' for a retry.
    Raises IngestionError for a contract violation. Does not write signal
    rows itself - the caller decides persistence, so the same
    validation/idempotency path serves local and cloud sinks."""
    event = validate_event(payload)
    return "accepted" if store.claim(project_id, event.event_id) else "duplicate"
