import hashlib
import json
import time

import httpx
import numpy as np
import pytest

from driftwatch_llm.agent import ipc
from driftwatch_llm.agent.runtime import ALIVE_WINDOW, AgentRuntime
from driftwatch_llm.api import Api
from driftwatch_llm.endpoints import Endpoints

P1 = "11111111-1111-4111-8111-111111111111"
KEY = "dw_1111111111_" + "1" * 64
EP = Endpoints(supabase_url="https://example.supabase.co", publishable_key="sb_publishable_test", web_origin="https://web.example")


class ThemeEmbedder:
    def encode(self, texts):
        out = []
        for t in texts:
            v = np.zeros(8)
            v[0 if t[:1] == "A" else 1] = 5.0
            v += np.frombuffer(hashlib.sha256(t.encode()).digest()[:8], dtype=np.uint8) / 255.0 - 0.5
            out.append(v)
        return np.stack(out)


class Clock:
    def __init__(self):
        self.now = time.time()

    def __call__(self):
        return self.now


class FakeSecrets:
    def __init__(self, keys=None):
        self.keys = dict(keys or {})

    def load(self, pid):
        return (self.keys[pid], "keychain") if pid in self.keys else None


def make(tmp_path, clock=None, factory=lambda: ThemeEmbedder(), handler=None, **kw):
    delivered = []

    def respond(request):
        delivered.append(json.loads(request.content))
        return httpx.Response(200, json="accepted")

    api = Api(EP, transport=httpx.MockTransport(handler or respond))
    rt = AgentRuntime(
        home=tmp_path / "home", embedder_factory=factory, api=api, secrets=FakeSecrets({P1: KEY}),
        clock=clock or Clock(), baseline_size=10, min_baseline=4, linger=30.0, sync_interval=0.05, **kw,
    )
    rt.delivered = delivered
    return rt


def wait_loaded(rt):
    rt.load_embedder_now()  # synchronous load for tests


def capture(rt, text, project=P1, model="gpt-x"):
    reply = rt.handle({"type": "capture", "project_id": project, "provider": "openai", "model": model, "text": text})
    rt.drain()  # the worker thread is not running in these tests: process what was queued, here
    return reply


def test_hello_and_heartbeat_register_clients_and_status_lists_them(tmp_path):
    rt = make(tmp_path)
    assert rt.handle({"type": "hello", "pid": 111, "python": "3.14.2", "sdks": {"openai": {"version": "1.40", "status": "patched"}}})["ok"]
    rt.handle({"type": "heartbeat", "pid": 111, "stats": {"captured": 7, "dropped": 1, "skipped_streaming": 2}})
    status = rt.handle({"type": "status"})["status"]
    (client,) = status["clients"]
    assert client["pid"] == 111 and client["python"] == "3.14.2"
    assert client["sdks"] == {"openai": {"version": "1.40", "status": "patched"}}
    assert client["stats"] == {"captured": 7, "dropped": 1, "skipped_streaming": 2}


def test_captures_build_the_baseline_and_show_up_in_status(tmp_path):
    rt = make(tmp_path)
    wait_loaded(rt)
    for i in range(7):
        assert capture(rt, f"A: answer {i}")["ok"] is True
    status = rt.handle({"type": "status"})["status"]
    assert status["embedder"] == "ready"
    assert status["projects"][P1]["baseline"] == {"frozen": False, "collected": 7, "target": 10, "window": 0}
    assert status["counters"]["captured"] == 7


def test_baseline_messages_freeze_and_reset(tmp_path):
    rt = make(tmp_path)
    wait_loaded(rt)
    for i in range(3):
        capture(rt, f"A: {i}")
    assert rt.handle({"type": "baseline", "action": "freeze", "project_id": P1}) == {"ok": True, "frozen": False}
    capture(rt, "A: 3")
    assert rt.handle({"type": "baseline", "action": "freeze", "project_id": P1}) == {"ok": True, "frozen": True}
    assert rt.handle({"type": "baseline", "action": "status", "project_id": P1})["baseline"]["frozen"] is True
    assert rt.handle({"type": "baseline", "action": "reset", "project_id": P1})["ok"] is True
    assert rt.handle({"type": "baseline", "action": "status", "project_id": P1})["baseline"]["collected"] == 0


def test_status_is_plain_json_and_never_contains_a_key(tmp_path):
    rt = make(tmp_path)
    wait_loaded(rt)
    capture(rt, "A: hello")
    text = json.dumps(rt.handle({"type": "status"}))
    assert KEY not in text and KEY[3:] not in text
    assert "hello" not in text  # response text is never reported either


def test_embedder_states_loading_ready_failed(tmp_path):
    rt = make(tmp_path)
    assert rt.handle({"type": "status"})["status"]["embedder"] == "loading"
    wait_loaded(rt)
    assert rt.handle({"type": "status"})["status"]["embedder"] == "ready"

    def broken():
        raise RuntimeError("model download failed at C:\\secret\\path")

    bad = make(tmp_path / "b", factory=broken)
    bad.load_embedder_now()
    st = bad.handle({"type": "status"})["status"]
    assert st["embedder"] == "failed: RuntimeError" and "secret" not in json.dumps(st)
    capture(bad, "A: x")
    assert bad.handle({"type": "status"})["status"]["counters"]["buffered_while_loading"] == 1


def test_the_agent_exits_after_the_linger_with_no_live_clients(tmp_path):
    clock = Clock()
    rt = make(tmp_path, clock)
    assert rt.tick() is False
    clock.now += 29
    assert rt.tick() is False
    clock.now += 2
    assert rt.tick() is True


def test_the_agent_exits_thirty_seconds_after_the_last_heartbeat(tmp_path):
    clock = Clock()
    rt = make(tmp_path, clock)
    rt.handle({"type": "hello", "pid": 5})
    for _ in range(10):
        clock.now += 20
        rt.handle({"type": "heartbeat", "pid": 5})
        assert rt.tick() is False  # a heartbeating client keeps it alive indefinitely
    clock.now += 29
    assert rt.tick() is False
    clock.now += 2
    assert rt.tick() is True
    assert rt.handle({"type": "status"})["status"]["clients"] == []  # silent for longer than ALIVE_WINDOW


def test_the_stop_message_ends_the_agent(tmp_path):
    rt = make(tmp_path)
    assert rt.handle({"type": "stop"})["ok"] is True
    assert rt.tick() is True


def test_full_stack_over_ipc_with_background_sync(tmp_path):
    clock = Clock()
    rt = make(tmp_path, clock)
    wait_loaded(rt)
    rt.start()
    try:
        client = ipc.IpcClient(tmp_path / "home")
        assert client.send({"type": "hello", "pid": 9})["ok"] is True
        for i in range(10):
            assert client.send({"type": "capture", "project_id": P1, "provider": "openai", "model": "m", "text": f"A: {i}"})["ok"]
        for i in range(5):  # the first emission needs five new responses and no waiting
            client.send({"type": "capture", "project_id": P1, "provider": "openai", "model": "m", "text": f"B: {i}"})
        deadline = time.time() + 5
        while time.time() < deadline and len(rt.delivered) < 2:
            time.sleep(0.05)
        signals = sorted(d["p_event"]["signal"] for d in rt.delivered)
        assert signals == ["combined_score", "embedding_drift"]
        assert all(d["p_api_key"] == KEY for d in rt.delivered)
        assert all("answer" not in json.dumps(d["p_event"]) for d in rt.delivered)
        client.close()
    finally:
        rt.shutdown()


def test_the_default_embedder_tries_the_local_cache_first_then_the_network(monkeypatch):
    from driftwatch_llm.agent import runtime
    from driftwatch_llm.core import embedding

    asked = []

    def fake(kind, local_only=False):
        asked.append((kind, local_only))
        if local_only:
            raise ValueError("not cached yet")
        return object()

    monkeypatch.setattr(embedding, "make_embedder", fake)
    monkeypatch.delenv("DRIFTWATCH_AGENT_EMBEDDER", raising=False)
    runtime._default_embedder()
    assert asked == [("onnx", True), ("onnx", False)]  # cached model: no network; otherwise download
    asked.clear()
    monkeypatch.setenv("DRIFTWATCH_AGENT_EMBEDDER", "sentence-transformers")
    monkeypatch.setattr(embedding, "make_embedder", lambda kind, local_only=False: asked.append((kind, local_only)) or object())
    runtime._default_embedder()
    assert asked == [("sentence-transformers", True)]  # the cached model loaded: no second attempt


def test_status_says_how_long_the_model_has_been_loading(tmp_path):
    clock = Clock()
    rt = make(tmp_path, clock)
    assert rt.handle({"type": "status"})["status"]["embedder_loading_seconds"] is None  # not started yet
    rt._embedder_started = clock.now - 90
    st = rt.handle({"type": "status"})["status"]
    assert st["embedder"] == "loading" and st["embedder_loading_seconds"] == 90.0
    wait_loaded(rt)
    assert rt.handle({"type": "status"})["status"]["embedder_loading_seconds"] is None


def test_the_ipc_thread_only_queues_the_embedding_happens_on_the_worker(tmp_path):
    import threading

    seen = []

    class Recording(ThemeEmbedder):
        def encode(self, texts):
            seen.append(threading.current_thread().name)
            return super().encode(texts)

    rt = make(tmp_path, factory=lambda: Recording())
    wait_loaded(rt)
    reply = rt.handle({"type": "capture", "project_id": P1, "provider": "openai", "model": "m", "text": "A: x"})
    assert reply["ok"] is True and seen == []  # answered before any embedding happened
    assert rt.handle({"type": "status"})["status"]["queued"] == 1
    rt.drain()
    assert seen == [threading.current_thread().name]
    assert rt.handle({"type": "status"})["status"]["queued"] == 0


def test_the_capture_queue_is_bounded_and_counts_what_it_drops(tmp_path):
    rt = make(tmp_path, capture_queue=3)
    for i in range(5):
        rt.handle({"type": "capture", "project_id": P1, "provider": "openai", "model": "m", "text": f"A: {i}"})
    assert rt.handle({"type": "status"})["status"]["counters"]["dropped_queue_full"] == 2
    rt.drain()
    assert rt.handle({"type": "status"})["status"]["queued"] == 0


def test_a_burst_over_ipc_is_answered_fast_and_fully_processed(tmp_path):
    rt = make(tmp_path)
    wait_loaded(rt)
    rt.start()
    try:
        client = ipc.IpcClient(tmp_path / "home")
        t0 = time.time()
        for i in range(150):
            assert client.send({"type": "capture", "project_id": P1, "provider": "openai", "model": "m", "text": f"A: {i}"})["ok"]
        assert time.time() - t0 < 5
        deadline = time.time() + 10
        while time.time() < deadline and rt.handle({"type": "status"})["status"]["queued"]:
            time.sleep(0.05)
        st = rt.handle({"type": "status"})["status"]
        assert st["queued"] == 0 and st["projects"][P1]["baseline"]["frozen"] is True
        client.close()
    finally:
        rt.shutdown()
