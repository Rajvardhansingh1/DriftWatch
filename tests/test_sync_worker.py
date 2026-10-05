import uuid
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from monitor.db.session import get_session, init_db
from monitor.sync.outbox import enqueue
from monitor.sync.worker import PermanentSyncError, TransientSyncError, drain, pending_count

T0 = datetime(2026, 10, 4, 9, 0, 0)


def make_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    init_db(engine=engine)
    return get_session(engine=engine)


def queue(session, n):
    ids = []
    for _ in range(n):
        e = {"event_id": str(uuid.uuid4()), "signal": "embedding_drift", "value": 0.1}
        enqueue(session, e, now=T0)
        ids.append(e["event_id"])
    return ids


def test_offline_then_resume_loses_nothing_and_duplicates_nothing():
    s = make_session()
    ids = queue(s, 5)
    delivered = []

    def offline(_event):
        raise TransientSyncError("network down")

    counts = drain(s, offline, now=T0)
    assert counts == {"sent": 0, "retry": 5, "quarantined": 0}
    assert pending_count(s) == 5  # still queued, nothing dropped

    def online(event):
        delivered.append(event["event_id"])

    counts = drain(s, online, now=T0 + timedelta(hours=1))
    assert counts["sent"] == 5
    assert sorted(delivered) == sorted(ids)  # every event exactly once
    assert pending_count(s) == 0


def test_permanent_error_quarantines_without_retry_or_delete():
    s = make_session()
    queue(s, 1)

    def rejected(_event):
        raise PermanentSyncError("401 invalid credential")

    counts = drain(s, rejected, now=T0)
    assert counts["quarantined"] == 1
    # Not retried even much later:
    calls = []
    drain(s, lambda e: calls.append(e), now=T0 + timedelta(days=30))
    assert calls == []


def test_partial_batch_failure_sends_the_rest():
    s = make_session()
    queue(s, 3)
    seen = []

    def flaky(event):
        if not seen:
            seen.append("first-fails")
            raise TransientSyncError("blip")
        seen.append(event["event_id"])

    counts = drain(s, flaky, now=T0)
    assert counts["retry"] == 1
    assert counts["sent"] == 2
