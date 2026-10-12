"""Ingestion contract enforcement. The implementation lives in driftwatch_llm.core.events so the
local agent validates events with exactly the code the server uses; this module re-exports it."""
from driftwatch_llm.core.events import (  # noqa: F401
    ALLOWED_FIELDS,
    ALLOWED_SIGNALS,
    MAX_ABS_VALUE,
    MAX_AGE,
    MAX_FUTURE,
    MAX_META_BYTES,
    MAX_META_DEPTH,
    MAX_META_KEYS,
    MAX_SOURCE_LEN,
    OPTIONAL_STRING_FIELDS,
    REQUIRED_FIELDS,
    IdempotencyStore,
    InMemoryIdempotencyStore,
    IngestionError,
    ValidatedEvent,
    _depth,
    ingest_event,
    validate_event,
)
