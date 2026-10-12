import hashlib
import time

import numpy as np
import pytest

from driftwatch_llm.agent.engine import Engine
from driftwatch_llm.agent.store import AgentStore
from driftwatch_llm.core.events import validate_event

P1 = "11111111-1111-4111-8111-111111111111"
P2 = "22222222-2222-4222-8222-222222222222"


class ThemeEmbedder:
    """Deterministic stand-in for MiniLM: a text starting with 'A' lands near one centre, 'B' near another."""

    dim = 8

    def __init__(self):
        self.calls = 0
        self.longest = 0

    def encode(self, texts):
        self.calls += len(texts)
        self.longest = max([self.longest] + [len(t) for t in texts])
        out = []
        for t in texts:
            centre = np.zeros(self.dim)
            centre[0 if t[:1] == "A" else 1] = 5.0
            noise = np.frombuffer(hashlib.sha256(t.encode()).digest()[: self.dim], dtype=np.uint8) / 255.0 - 0.5
            out.append(centre + noise)
        return np.stack(out)


class Clock:
    def __init__(self, now=None):
        self.now = time.time() if now is None else now

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(tmp_path, clock):
    s = AgentStore(tmp_path / "s" / "agent.sqlite3", clock=clock)
    yield s
    s.close()


def make(store, clock, embedder=None, **kw):
    kw.setdefault("baseline_size", 10)
    kw.setdefault("min_baseline", 4)
    return Engine(store, embedder or ThemeEmbedder(), clock=clock, **kw)


def feed(engine, clock, project, prefix, n, start=0, step=1.0):
    events = []
    for i in range(start, start + n):
        clock.now += step
        events += engine.capture(project, f"{prefix}: answer number {i}", provider="openai", model="gpt-x")
    return events


def test_no_signal_while_the_baseline_is_building_then_it_freezes_and_persists(store, clock):
    e = make(store, clock)
    assert feed(e, clock, P1, "A", 9) == []
    assert e.baseline_status(P1) == {"frozen": False, "collected": 9, "target": 10, "window": 0}
    assert store.load_baseline(P1) is None
    feed(e, clock, P1, "A", 1, start=9)
    assert e.baseline_status(P1)["frozen"] is True
    assert store.load_baseline(P1).shape == (10, 8)


def test_first_signal_needs_five_new_responses_after_the_baseline(store, clock):
    e = make(store, clock)
    feed(e, clock, P1, "A", 10)
    assert feed(e, clock, P1, "A", 4, start=10) == []
    events = feed(e, clock, P1, "A", 1, start=14)
    assert [ev["signal"] for ev in events] == ["embedding_drift", "combined_score"]


def test_a_shifted_distribution_scores_far_higher_than_a_stable_one(store, clock, tmp_path):
    stable = make(store, clock)
    feed(stable, clock, P1, "A", 10)
    s = feed(stable, clock, P1, "A", 5, start=10)[0]["value"]
    other = AgentStore(tmp_path / "o" / "agent.sqlite3", clock=clock)
    shifted = make(other, clock)
    feed(shifted, clock, P1, "A", 10)
    h = feed(shifted, clock, P1, "B", 5)[0]["value"]
    other.close()
    # A 5-response window has a noise floor (the biased MMD estimator), so stable is not ~0; shifted is still far above it.
    assert h > s + 0.5 and h > 3 * s


def test_each_drift_value_says_whether_its_window_is_full(store, clock):
    e = make(store, clock)
    feed(e, clock, P1, "A", 10)
    first = feed(e, clock, P1, "A", 5, start=10)[0]
    assert first["meta"]["current_n"] == 5 and first["meta"]["window_full"] is False
    last = None
    for batch in range(4):  # 5 more responses a minute apart, until the window of 20 is full
        clock.now += 60
        events = feed(e, clock, P1, "A", 5, start=15 + batch * 5, step=0.1)
        last = events[0] if events else last
    assert last["meta"]["current_n"] == 20 and last["meta"]["window_full"] is True


def test_emission_is_throttled_to_one_a_minute(store, clock):
    e = make(store, clock)
    feed(e, clock, P1, "A", 10)
    assert len(feed(e, clock, P1, "A", 5, start=10)) == 2
    assert feed(e, clock, P1, "A", 8, start=15, step=1.0) == []  # plenty of new responses, but only 8 s later
    clock.now += 60
    assert len(feed(e, clock, P1, "A", 1, start=23)) == 2


def test_events_are_valid_numbers_only_and_carry_no_alert_in_embedding_only_mode(store, clock):
    e = make(store, clock)
    feed(e, clock, P1, "A", 10)
    events = feed(e, clock, P1, "B", 5)
    assert len(events) == 2
    for ev in events:
        validated = validate_event(ev)
        assert validated.source == "agent" and validated.content_capture is False
        assert set(ev) <= {"schema_version", "event_id", "occurred_at", "source", "signal", "value", "meta", "content_capture"}
    drift, combined = events
    assert drift["meta"]["baseline_n"] == 10 and drift["meta"]["current_n"] == 5
    assert drift["meta"]["models"] == {"gpt-x": 5}
    assert combined["meta"]["mode"] == "embedding_only"
    assert "alert" not in combined["meta"] and "alert" not in drift["meta"]
    assert 0.0 <= combined["value"] <= 1.0
    assert len({ev["event_id"] for ev in events}) == 2
    assert store.pending_count() == 2
    assert [r["value"] for r in store.recent_signals(P1, "embedding_drift")] == [drift["value"]]


def test_no_response_text_reaches_the_store_the_outbox_or_disk(store, clock, tmp_path):
    e = make(store, clock)
    secret = "PLANTED-SECRET-9f3c1"
    for i in range(20):
        clock.now += 10
        e.capture(P1, f"A: {secret} number {i}", provider="openai", model="m")
    store.close()
    blobs = b"".join(p.read_bytes() for p in (tmp_path / "s").rglob("*") if p.is_file())
    assert secret.encode() not in blobs
    assert b"answer" not in blobs
    assert len(blobs) > 1000  # we really did scan something


def test_each_response_is_embedded_once_and_the_window_stays_bounded(store, clock):
    emb = ThemeEmbedder()
    e = make(store, clock, emb)
    feed(e, clock, P1, "A", 60)
    assert emb.calls == 60
    assert e.baseline_status(P1)["window"] == 20


def test_long_responses_are_truncated_and_empty_ones_ignored(store, clock):
    emb = ThemeEmbedder()
    e = make(store, clock, emb)
    e.capture(P1, "A" + "x" * 50_000)
    assert emb.longest == 8000
    for junk in ["", "   \n", None, 42, b"bytes"]:
        assert e.capture(P1, junk) == []
    assert store.counter("ignored_empty") == 5
    assert emb.calls == 1


def test_early_freeze_needs_the_minimum_and_reset_starts_over(store, clock):
    e = make(store, clock)
    feed(e, clock, P1, "A", 3)
    assert e.freeze(P1) is False and e.baseline_status(P1)["frozen"] is False
    feed(e, clock, P1, "A", 1, start=3)
    assert e.freeze(P1) is True
    assert store.load_baseline(P1).shape == (4, 8)
    assert e.baseline_status(P1) == {"frozen": True, "collected": 4, "target": 10, "window": 0}
    e.reset(P1)
    assert store.load_baseline(P1) is None
    assert e.baseline_status(P1) == {"frozen": False, "collected": 0, "target": 10, "window": 0}


def test_projects_are_isolated(store, clock):
    e = make(store, clock)
    feed(e, clock, P1, "A", 10)
    feed(e, clock, P2, "A", 4)
    assert e.baseline_status(P1)["frozen"] and not e.baseline_status(P2)["frozen"]
    assert store.load_baseline(P2) is None


def test_a_restarted_engine_reuses_the_saved_baseline(store, clock):
    feed(make(store, clock), clock, P1, "A", 10)
    again = make(store, clock)
    assert again.baseline_status(P1)["frozen"] is True
    assert len(feed(again, clock, P1, "A", 5)) == 2


def test_an_embedder_failure_is_counted_and_does_not_stop_the_engine(store, clock):
    class Flaky(ThemeEmbedder):
        def encode(self, texts):
            if "boom" in texts[0]:
                raise RuntimeError("model exploded")
            return super().encode(texts)

    e = make(store, clock, Flaky())
    assert e.capture(P1, "A: boom") == []
    assert store.counter("embed_errors") == 1
    feed(e, clock, P1, "A", 10)
    assert e.baseline_status(P1)["frozen"] is True


def test_without_an_embedder_nothing_is_lost_silently(store, clock):
    e = Engine(store, None, clock=clock, baseline_size=10, min_baseline=4)
    assert e.capture(P1, "A: hello") == []
    assert store.counter("dropped_no_embedder") == 1
    e.set_embedder(ThemeEmbedder())
    e.capture(P1, "A: hello again")
    assert e.baseline_status(P1)["collected"] == 1
