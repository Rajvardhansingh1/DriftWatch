import sqlite3
import threading

import numpy as np
import pytest

from driftwatch_llm.agent.store import AgentStore
from driftwatch_llm.core.backoff import MAX_ATTEMPTS

P1 = "11111111-1111-4111-8111-111111111111"
P2 = "22222222-2222-4222-8222-222222222222"


class Clock:
    def __init__(self, now=1_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(tmp_path, clock):
    s = AgentStore(tmp_path / "agent.sqlite3", clock=clock)
    yield s
    s.close()


def event(n: int) -> dict:
    return {"event_id": f"00000000-0000-4000-8000-{n:012d}", "signal": "embedding_drift", "value": 0.1}


def test_creates_the_schema_in_wal_mode(tmp_path):
    s = AgentStore(tmp_path / "x.sqlite3")
    s.close()
    con = sqlite3.connect(tmp_path / "x.sqlite3")
    assert con.execute("pragma journal_mode").fetchone()[0].lower() == "wal"
    tables = {r[0] for r in con.execute("select name from sqlite_master where type = 'table'")}
    assert {"signals", "outbox", "parked", "counters"} <= tables


def test_signals_are_newest_first_limited_and_per_project(store, clock):
    for i in range(5):
        clock.now += 1
        store.add_signal(P1, "embedding_drift", i / 10, {"n": i})
    store.add_signal(P2, "embedding_drift", 0.99, {})
    rows = store.recent_signals(P1, "embedding_drift", limit=3)
    assert [r["value"] for r in rows] == [0.4, 0.3, 0.2]
    assert rows[0]["meta"] == {"n": 4}
    assert [r["value"] for r in store.recent_signals(P2, "embedding_drift")] == [0.99]
    assert store.recent_signals(P1, "combined_score") == []


def test_enqueue_is_idempotent_on_event_id(store):
    assert store.enqueue(P1, event(1)) is True
    assert store.enqueue(P1, event(1)) is False
    assert store.pending_count() == 1


def test_due_honours_the_schedule_and_returns_the_payload(store, clock):
    store.enqueue(P1, event(1))
    rows = store.due()
    assert [(r.event_id, r.project_id, r.payload["value"]) for r in rows] == [(event(1)["event_id"], P1, 0.1)]
    store.mark_failed(event(1)["event_id"], "boom", permanent=False)
    assert store.due() == []  # rescheduled into the future
    clock.now += 3600
    assert len(store.due()) == 1


def test_transient_failure_backs_off_and_honours_retry_after(store, clock):
    store.enqueue(P1, event(1))
    store.mark_failed(event(1)["event_id"], "429", permanent=False, retry_after=120)
    clock.now += 119
    assert store.due() == []
    clock.now += 2
    assert len(store.due()) == 1


def test_permanent_failure_and_too_many_attempts_quarantine_but_never_delete(store, clock):
    store.enqueue(P1, event(1))
    store.mark_failed(event(1)["event_id"], "422", permanent=True)
    assert store.counts()["quarantined"] == 1
    store.enqueue(P1, event(2))
    for _ in range(MAX_ATTEMPTS):
        clock.now += 10_000
        store.mark_failed(event(2)["event_id"], "5xx", permanent=False)
    assert store.counts()["quarantined"] == 2
    assert store.pending_count() == 0
    assert store.due() == []


def test_mark_sent_moves_to_sent_and_keeps_the_row(store):
    store.enqueue(P1, event(1))
    store.mark_sent(event(1)["event_id"])
    assert store.counts()["sent"] == 1 and store.due() == []


def test_parking_a_project_pauses_only_that_project(store):
    store.enqueue(P1, event(1))
    store.enqueue(P2, event(2))
    store.park_project(P1, "auth_failed")
    assert [r.project_id for r in store.due()] == [P2]
    assert store.parked() == {P1: "auth_failed"}
    assert store.pending_count() == 2  # nothing is lost
    store.unpark_project(P1)
    assert {r.project_id for r in store.due()} == {P1, P2}
    assert store.parked() == {}


def test_pending_cap_drops_the_oldest_and_counts_them(tmp_path, clock):
    s = AgentStore(tmp_path / "cap.sqlite3", max_pending=3, clock=clock)
    for i in range(1, 6):
        clock.now += 1
        s.enqueue(P1, event(i))
    assert s.pending_count() == 3
    assert [r.event_id for r in s.due(limit=10)] == [event(3)["event_id"], event(4)["event_id"], event(5)["event_id"]]
    assert s.counter("dropped_total") == 2
    s.close()


def test_baseline_round_trips_as_float32_vectors_only(store, tmp_path):
    vectors = np.random.default_rng(0).normal(size=(7, 5))
    assert store.load_baseline(P1) is None
    store.save_baseline(P1, vectors)
    loaded = store.load_baseline(P1)
    assert loaded.dtype == np.float32 and loaded.shape == (7, 5)
    assert np.allclose(loaded, vectors, atol=1e-6)
    with np.load(next((tmp_path / "baselines").glob("*.npz"))) as z:
        assert list(z.keys()) == ["vectors"]
    assert store.load_baseline(P2) is None
    store.clear_baseline(P1)
    assert store.load_baseline(P1) is None


def test_baseline_file_names_cannot_escape_the_directory(store, tmp_path):
    with pytest.raises(ValueError):
        store.save_baseline("../../evil", np.zeros((1, 2)))


def test_counters(store):
    assert store.counter("x") == 0
    store.bump("x")
    store.bump("x", 4)
    assert store.counter("x") == 5 and store.counters()["x"] == 5


def test_prune_removes_old_signals_and_old_sent_rows_only(store, clock):
    store.add_signal(P1, "embedding_drift", 0.1, {}, ts=clock.now - 31 * 86400)
    store.add_signal(P1, "embedding_drift", 0.2, {}, ts=clock.now - 1 * 86400)
    store.enqueue(P1, event(1))
    store.enqueue(P1, event(2))
    store.enqueue(P1, event(3))
    store.mark_sent(event(1)["event_id"])
    clock.now += 2 * 86400
    store.mark_sent(event(2)["event_id"])
    store.prune()
    assert [r["value"] for r in store.recent_signals(P1, "embedding_drift")] == [0.2]
    counts = store.counts()
    assert counts["sent"] == 1 and counts["pending"] == 1  # the day-old sent row went; the fresh one stayed


def test_concurrent_writers_do_not_lose_or_corrupt_rows(store):
    def work(project, base):
        for i in range(150):
            store.add_signal(project, "embedding_drift", i / 1000, {})
            store.enqueue(project, event(base + i))

    threads = [threading.Thread(target=work, args=(P1, 0)), threading.Thread(target=work, args=(P2, 10_000))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(store.recent_signals(P1, "embedding_drift", limit=1000)) == 150
    assert len(store.recent_signals(P2, "embedding_drift", limit=1000)) == 150
    assert store.pending_count() == 300


def test_signals_since_and_projects_for_the_local_dashboard(tmp_path):
    clock = [1000.0]
    store = AgentStore(tmp_path / "a.sqlite3", clock=lambda: clock[0])
    for i, ts in enumerate([100.0, 500.0, 900.0]):
        store.add_signal("p1", "embedding_drift", 0.1 * (i + 1), {"n": i}, ts=ts)
    store.add_signal("p2", "combined_score", 0.5, ts=900.0)
    rows = store.signals_since("p1", "embedding_drift", since=400.0, limit=10)
    assert [r["ts"] for r in rows] == [500.0, 900.0]  # oldest first, the old one excluded
    assert [r["ts"] for r in store.signals_since("p1", "embedding_drift", since=0.0, limit=2)] == [500.0, 900.0]  # the latest two
    assert store.projects() == ["p1", "p2"]
    store.close()
