import json
import logging
import time

import httpx
import pytest

from driftwatch_llm.agent.store import AgentStore
from driftwatch_llm.agent.sync import SyncWorker
from driftwatch_llm.api import Api
from driftwatch_llm.endpoints import Endpoints

P1 = "11111111-1111-4111-8111-111111111111"
P2 = "22222222-2222-4222-8222-222222222222"
KEY1 = "dw_1111111111_" + "1" * 64
KEY2 = "dw_2222222222_" + "2" * 64
EP = Endpoints(supabase_url="https://example.supabase.co", publishable_key="sb_publishable_test", web_origin="https://web.example")


class Clock:
    def __init__(self):
        self.now = time.time()

    def __call__(self):
        return self.now


class FakeSecrets:
    def __init__(self, keys):
        self.keys = dict(keys)

    def load(self, project_id):
        key = self.keys.get(project_id)
        return (key, "keychain") if key else None


def event(n, signal="embedding_drift", occurred=None):
    return {
        "schema_version": 1,
        "event_id": f"00000000-0000-4000-8000-{n:012d}",
        "occurred_at": occurred or time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "source": "agent",
        "signal": signal,
        "value": 0.2,
        "meta": {},
        "content_capture": False,
    }


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(tmp_path, clock):
    s = AgentStore(tmp_path / "a.sqlite3", clock=clock)
    yield s
    s.close()


def worker(store, clock, handler, keys=None):
    calls = []

    def wrapped(request):
        calls.append(json.loads(request.content))
        return handler(request, calls)

    api = Api(EP, transport=httpx.MockTransport(wrapped))
    secrets = FakeSecrets({P1: KEY1, P2: KEY2} if keys is None else keys)
    return SyncWorker(store, api, secrets, clock=clock), calls


def ok(word="accepted"):
    return lambda request, calls: httpx.Response(200, json=word)


def test_sends_each_event_with_its_projects_key_and_marks_it_sent(store, clock):
    store.enqueue(P1, event(1))
    store.enqueue(P2, event(2))
    w, calls = worker(store, clock, ok())
    assert w.drain_once()["sent"] == 2
    assert {c["p_api_key"] for c in calls} == {KEY1, KEY2}
    assert store.counts()["sent"] == 2 and store.pending_count() == 0
    assert w.status()["sent_total"] == 2 and w.status()["last_success_at"] == clock.now


def test_a_duplicate_answer_counts_as_delivered(store, clock):
    store.enqueue(P1, event(1))
    w, _ = worker(store, clock, ok("duplicate"))
    assert w.drain_once()["sent"] == 1 and store.counts()["sent"] == 1


def test_a_revoked_key_parks_the_project_without_losing_events_then_a_new_key_resumes(store, clock):
    store.enqueue(P1, event(1))
    revoked = lambda request, calls: httpx.Response(401, json={"code": "PT401", "message": "unauthorized"})  # noqa: E731
    w, calls = worker(store, clock, revoked)
    assert w.drain_once()["parked"] == 1
    assert store.parked() == {P1: "auth_failed"} and store.pending_count() == 1
    n = len(calls)
    w.drain_once()
    assert len(calls) == n  # parked: nothing is sent while the same key is stored
    w._secrets.keys[P1] = "dw_9999999999_" + "9" * 64  # the user ran `driftwatch login`
    w._api = Api(EP, transport=httpx.MockTransport(lambda r: httpx.Response(200, json="accepted")))
    assert w.drain_once()["sent"] == 1 and store.parked() == {}


def test_no_stored_key_parks_as_needs_login_and_resumes_when_a_key_appears(store, clock):
    store.enqueue(P1, event(1))
    w, calls = worker(store, clock, ok(), keys={})
    assert w.drain_once()["no_key"] == 1 and calls == []
    assert store.parked() == {P1: "needs_login"}
    w._secrets.keys[P1] = KEY1
    assert w.drain_once()["sent"] == 1


def test_rate_limit_honours_retry_after(store, clock):
    store.enqueue(P1, event(1))
    limited = lambda request, calls: httpx.Response(429, json={"code": "PT429"}, headers={"Retry-After": "120"})  # noqa: E731
    w, _ = worker(store, clock, limited)
    assert w.drain_once()["retry"] == 1
    clock.now += 119
    assert store.due() == []
    clock.now += 2
    assert len(store.due()) == 1


def test_server_errors_back_off_and_stop_the_round(store, clock):
    store.enqueue(P1, event(1))
    store.enqueue(P1, event(2))
    down = lambda request, calls: httpx.Response(503, json={"message": "down"})  # noqa: E731
    w, calls = worker(store, clock, down)
    counts = w.drain_once()
    assert counts["retry"] == 1 and len(calls) == 1  # did not hammer a struggling server
    assert store.pending_count() == 2 and store.counts()["quarantined"] == 0


def test_a_rejected_event_is_quarantined_and_the_next_one_still_goes(store, clock):
    store.enqueue(P1, event(1))
    store.enqueue(P1, event(2))
    seen = []

    def handler(request, calls):
        seen.append(1)
        if len(seen) == 1:
            return httpx.Response(422, json={"code": "PT422", "message": "unknown signal"})
        return httpx.Response(200, json="accepted")

    w, _ = worker(store, clock, handler)
    counts = w.drain_once()
    assert counts["quarantined"] == 1 and counts["sent"] == 1
    assert store.counts()["quarantined"] == 1


def test_an_event_that_fails_the_local_contract_is_quarantined_before_any_request(store, clock):
    store.enqueue(P1, event(1, signal="not_a_signal"))
    store.enqueue(P1, event(2, occurred="2020-01-01T00:00:00+00:00"))
    w, calls = worker(store, clock, ok())
    counts = w.drain_once()
    assert counts["invalid"] == 2 and calls == []
    assert store.counts()["quarantined"] == 2 and store.counter("invalid_events") == 2


def test_a_gateway_401_is_not_treated_as_a_revoked_key(store, clock):
    store.enqueue(P1, event(1))
    w, _ = worker(store, clock, lambda request, calls: httpx.Response(401, json={"message": "Invalid API key"}))
    assert w.drain_once()["retry"] == 1
    assert store.parked() == {}


def test_nothing_leaks_the_key(store, clock, caplog):
    caplog.set_level(logging.DEBUG)
    store.enqueue(P1, event(1))
    store.enqueue(P2, event(2))
    w, _ = worker(store, clock, lambda request, calls: httpx.Response(401, json={"code": "PT401"}))
    w.drain_once()
    dump = json.dumps(w.status()) + caplog.text + json.dumps(store.counters()) + json.dumps(store.parked())
    assert KEY1 not in dump and KEY2 not in dump
    assert KEY1[3:] not in dump and KEY2[3:] not in dump


def test_status_reports_pending_parked_and_the_last_error_in_plain_words(store, clock):
    store.enqueue(P1, event(1))
    w, _ = worker(store, clock, lambda request, calls: httpx.Response(500, json={"message": "boom"}))
    w.drain_once()
    st = w.status()
    assert st["pending"] == 1 and st["parked"] == {}
    assert "problem" in st["last_error"] and "boom" not in st["last_error"]
