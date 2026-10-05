import uuid

import pytest

from monitor.cloud.ingest import (
    IngestionError,
    InMemoryIdempotencyStore,
    ingest_event,
    validate_event,
)

PROJECT = "11111111-1111-1111-1111-111111111111"


def valid_event(**overrides):
    event = {
        "schema_version": 1,
        "event_id": str(uuid.uuid4()),
        "occurred_at": "2026-09-30T10:00:00+00:00",
        "source": "driftwatch-demo-bot",
        "signal": "embedding_drift",
        "value": 0.25,
        "meta": {"n": 3},
    }
    event.update(overrides)
    return event


def test_valid_event_is_accepted_once_then_reported_duplicate():
    store = InMemoryIdempotencyStore()
    event = valid_event()
    assert ingest_event(event, PROJECT, store) == "accepted"
    assert ingest_event(event, PROJECT, store) == "duplicate"


def test_same_event_id_in_another_project_is_not_a_duplicate():
    store = InMemoryIdempotencyStore()
    event = valid_event()
    assert ingest_event(event, PROJECT, store) == "accepted"
    assert ingest_event(event, "22222222-2222-2222-2222-222222222222", store) == "accepted"


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"schema_version": 2}, "unsupported schema_version"),
        ({"event_id": "not-a-uuid"}, "event_id must be a UUID"),
        ({"occurred_at": "yesterday"}, "ISO-8601"),
        ({"occurred_at": "2026-09-30T10:00:00"}, "timezone offset"),
        ({"signal": "made_up"}, "unknown signal"),
        ({"value": float("nan")}, "finite number"),
        ({"value": True}, "finite number"),
        ({"source": ""}, "source must be"),
        ({"meta": "not-an-object"}, "meta must be an object"),
        ({"meta": {"blob": "x" * 5000}}, "exceeds size limit"),
        ({"content_capture": "yes"}, "content_capture must be a boolean"),
    ],
)
def test_contract_violations_are_rejected(overrides, message):
    with pytest.raises(IngestionError, match=message):
        validate_event(valid_event(**overrides))


def test_unknown_field_is_rejected_not_silently_kept():
    with pytest.raises(IngestionError, match="unknown field"):
        validate_event(valid_event(injected_admin_flag=True))


def test_missing_required_field_is_rejected():
    event = valid_event()
    del event["signal"]
    with pytest.raises(IngestionError, match="missing required"):
        validate_event(event)


def test_non_object_payload_is_rejected():
    with pytest.raises(IngestionError, match="JSON object"):
        validate_event(["not", "an", "object"])


def test_content_capture_defaults_to_false():
    assert validate_event(valid_event()).content_capture is False
