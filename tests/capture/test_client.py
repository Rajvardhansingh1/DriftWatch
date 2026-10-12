import time

import pytest

from driftwatch_llm.agent import ipc
from driftwatch_llm.capture import wrappers
from driftwatch_llm.capture.client import CaptureClient

PID = "11111111-1111-4111-8111-111111111111"


@pytest.fixture(autouse=True)
def clean():
    wrappers.reset_for_tests()
    yield
    wrappers.reset_for_tests()


@pytest.fixture
def home(tmp_path):
    return tmp_path / "home"


class Recorder:
    def __init__(self):
        self.messages = []

    def __call__(self, msg):
        self.messages.append(msg)
        return {"ok": True}

    def of(self, kind):
        return [m for m in self.messages if m["type"] == kind]


def wait_for(cond, seconds=5.0):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.02)
    return False


def record(text="a response", model="gpt-x"):
    return {"provider": "openai", "model": model, "text": text, "latency_ms": 12.5}


def make(home, **kw):
    kw.setdefault("heartbeat_every", 0.1)
    kw.setdefault("ensure_every", 60.0)
    return CaptureClient(PID, home=home, **kw)


def test_records_reach_the_agent_after_a_hello_and_a_heartbeat_with_stats(home):
    rec = Recorder()
    server = ipc.IpcServer(home, rec)
    server.start()
    client = make(home)
    client.start()
    try:
        client.submit(record("first"))
        client.submit(record("second"))
        assert wait_for(lambda: len(rec.of("capture")) == 2)
        assert [m["text"] for m in rec.of("capture")] == ["first", "second"]
        cap = rec.of("capture")[0]
        assert cap["project_id"] == PID and cap["provider"] == "openai" and cap["model"] == "gpt-x" and cap["latency_ms"] == 12.5
        assert rec.messages[0]["type"] == "hello"  # the agent hears who is talking before any capture
        hello = rec.of("hello")[0]
        assert hello["project_id"] == PID and isinstance(hello["pid"], int) and hello["python"].count(".") == 2
        assert wait_for(lambda: rec.of("heartbeat"))
        stats = rec.of("heartbeat")[-1]["stats"]
        assert stats["sent"] == 2 and set(stats) <= {"captured", "skipped_streaming", "skipped_other", "errors", "dropped", "sent", "send_failures"}
    finally:
        client.stop()
        server.stop()


def test_a_changed_sdk_status_is_announced_with_a_new_hello(home, monkeypatch):
    rec = Recorder()
    server = ipc.IpcServer(home, rec)
    server.start()
    client = make(home)
    client.start()
    try:
        assert wait_for(lambda: len(rec.of("hello")) == 1)
        wrappers._sdk["openai"] = {"version": "3.29.0", "status": "patched"}
        client.submit(record())
        assert wait_for(lambda: len(rec.of("hello")) == 2)
        assert rec.of("hello")[-1]["sdks"] == {"openai": {"version": "3.29.0", "status": "patched"}}
    finally:
        client.stop()
        server.stop()


def test_submit_never_blocks_and_the_queue_is_bounded_when_no_agent_runs(home, monkeypatch):
    from driftwatch_llm.agent import launcher

    monkeypatch.setattr(launcher, "ensure_agent", lambda *a, **k: False)
    client = make(home, queue_size=50)
    client.start()
    try:
        start = time.perf_counter()
        for i in range(5000):
            client.submit(record(f"r{i}"))
        assert (time.perf_counter() - start) / 5000 < 0.001
        assert client.queue_len() <= 50
        assert client.stats()["dropped"] >= 4900
    finally:
        client.stop()


def test_a_missing_agent_is_started_but_not_more_than_once_per_interval(home, monkeypatch):
    from driftwatch_llm.agent import launcher

    calls = []
    monkeypatch.setattr(launcher, "ensure_agent", lambda *a, **k: calls.append(1) or False)
    client = make(home, ensure_every=60.0)
    client.start()
    try:
        client.submit(record())
        assert wait_for(lambda: len(calls) == 1)
        time.sleep(2.5)
        assert len(calls) == 1
    finally:
        client.stop()


def test_records_queued_before_the_agent_exists_are_delivered_when_it_appears(home, monkeypatch):
    from driftwatch_llm.agent import launcher

    monkeypatch.setattr(launcher, "ensure_agent", lambda *a, **k: False)
    client = make(home)
    client.start()
    rec = Recorder()
    server = None
    try:
        for i in range(3):
            client.submit(record(f"early {i}"))
        time.sleep(0.5)
        server = ipc.IpcServer(home, rec)
        server.start()
        assert wait_for(lambda: len(rec.of("capture")) == 3)
        assert [m["text"] for m in rec.of("capture")] == ["early 0", "early 1", "early 2"]
    finally:
        client.stop()
        if server:
            server.stop()


def test_it_reconnects_after_the_agent_restarts(home):
    rec = Recorder()
    server = ipc.IpcServer(home, rec)
    server.start()
    client = make(home)
    client.start()
    try:
        client.submit(record("before"))
        assert wait_for(lambda: len(rec.of("capture")) == 1)
        server.stop()
        rec2 = Recorder()
        server = ipc.IpcServer(home, rec2)
        server.start()
        assert wait_for(lambda: rec2.of("hello"), 8)
        client.submit(record("after"))
        assert wait_for(lambda: any(m["text"] == "after" for m in rec2.of("capture")), 8)
    finally:
        client.stop()
        server.stop()


def test_stop_ends_the_thread_quickly_and_it_is_a_daemon(home):
    client = make(home)
    client.start()
    assert client._thread.daemon is True
    start = time.time()
    client.stop()
    assert time.time() - start < 3.0 and not client._thread.is_alive()
