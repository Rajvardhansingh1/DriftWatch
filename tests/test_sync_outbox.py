import uuid
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from monitor.db.models import SyncOutbox
from monitor.db.session import get_session, init_db
from monitor.sync.outbox import MAX_ATTEMPTS, backoff_seconds, due, enqueue, mark_failed, mark_sent

T0 = datetime(2026, 9, 30, 12, 0, 0)


def make_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    init_db(engine=engine)
    return get_session(engine=engine)


def event():
    return {"event_id": str(uuid.uuid4()), "signal": "embedding_drift", "value": 0.1}


def test_enqueue_is_idempotent_on_event_id():
    s = make_session()
    e = event()
    assert enqueue(s, e, now=T0) is True
    assert enqueue(s, e, now=T0) is False
    assert s.query(SyncOutbox).count() == 1


def test_due_returns_only_rows_whose_time_has_come():
    s = make_session()
    enqueue(s, event(), now=T0)
    enqueue(s, event(), now=T0 + timedelta(hours=1))
    assert len(due(s, now=T0)) == 1
    assert len(due(s, now=T0 + timedelta(hours=2))) == 2


def test_mark_sent_removes_row_from_due_but_keeps_it():
    s = make_session()
    enqueue(s, event(), now=T0)
    row = due(s, now=T0)[0]
    mark_sent(s, row)
    assert due(s, now=T0 + timedelta(days=1)) == []
    assert s.query(SyncOutbox).filter_by(status="sent").count() == 1


def test_transient_failure_reschedules_with_backoff_not_drop():
    s = make_session()
    enqueue(s, event(), now=T0)
    row = due(s, now=T0)[0]
    mark_failed(s, row, "network down", permanent=False, now=T0, rng=lambda: 0.0)
    assert row.status == "pending"
    assert row.attempts == 1
    assert row.next_attempt_at > T0
    assert row.last_error == "network down"


def test_permanent_failure_quarantines_and_keeps_the_record():
    s = make_session()
    enqueue(s, event(), now=T0)
    row = due(s, now=T0)[0]
    mark_failed(s, row, "401 invalid project key", permanent=True, now=T0)
    assert row.status == "quarantined"
    assert s.query(SyncOutbox).count() == 1  # never deleted


def test_exhausting_attempts_quarantines():
    s = make_session()
    enqueue(s, event(), now=T0)
    row = due(s, now=T0)[0]
    for _ in range(MAX_ATTEMPTS):
        mark_failed(s, row, "timeout", permanent=False, now=T0, rng=lambda: 0.0)
    assert row.status == "quarantined"


def test_backoff_is_bounded_and_monotonic_in_expectation():
    assert backoff_seconds(1, rng=lambda: 0.0) < backoff_seconds(3, rng=lambda: 0.0)
    assert backoff_seconds(50, rng=lambda: 1.0) <= 15 * 60
