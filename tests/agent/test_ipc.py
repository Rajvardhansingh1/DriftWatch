import hashlib
import hmac
import json
import os
import pickle
import re
import sys
import threading
import time
from multiprocessing.connection import Client
from pathlib import Path

import pytest

from driftwatch_llm.agent import ipc

PID = "11111111-1111-4111-8111-111111111111"
POSIX = sys.platform != "win32"


@pytest.fixture
def home(tmp_path):
    return tmp_path / "home"


@pytest.fixture
def server(home):
    seen = []

    def handler(msg):
        seen.append(msg)
        return {"ok": True, "echo": msg["type"]}

    srv = ipc.IpcServer(home, handler)
    srv.start()
    yield srv, seen
    srv.stop()


def raw_connect(home):
    """A client that does the handshake by hand, so tests can send arbitrary bytes afterwards."""
    key = ipc.load_or_create_authkey(home)
    conn = Client(ipc.address_for(home), family=ipc.FAMILY)
    nonce = conn.recv_bytes(maxlength=64)[3:]
    conn.send_bytes(hmac.new(key, nonce, hashlib.sha256).digest())
    assert conn.recv_bytes(maxlength=8) == b"OK"
    return conn


def roundtrip(conn, payload: bytes):
    conn.send_bytes(payload)
    assert conn.poll(3)
    return json.loads(conn.recv_bytes())


GOOD = [
    {"type": "hello", "pid": 123, "python": "3.14.2", "sdks": {"openai": {"version": "1.40.0", "status": "patched"}}},
    {"type": "heartbeat", "pid": 123},
    {"type": "heartbeat", "pid": 123, "stats": {"captured": 5, "dropped": 0}},
    {"type": "capture", "project_id": PID, "provider": "openai", "model": "gpt-x", "text": "hello", "latency_ms": 12.5},
    {"type": "capture", "project_id": PID, "provider": "groq", "model": None, "text": "hi", "latency_ms": None},
    {"type": "status"},
    {"type": "baseline", "action": "freeze", "project_id": PID},
    {"type": "stop"},
]


@pytest.mark.parametrize("msg", GOOD, ids=[m["type"] + str(i) for i, m in enumerate(GOOD)])
def test_valid_messages_round_trip(server, home, msg):
    srv, seen = server
    client = ipc.IpcClient(home)
    reply = client.send(msg)
    assert reply == {"ok": True, "echo": msg["type"]}
    assert seen[-1] == msg
    client.close()


def test_one_connection_serves_many_requests(server, home):
    client = ipc.IpcClient(home)
    for _ in range(20):
        assert client.send({"type": "heartbeat", "pid": 1})["ok"] is True
    client.close()


@pytest.mark.parametrize(
    "bad",
    [
        b"not json",
        b"[1, 2]",
        b'"just a string"',
        b'{"type": "explode"}',
        b'{"nope": 1}',
        b'{"type": "capture", "project_id": "not-a-uuid", "provider": "openai", "model": "m", "text": "x"}',
        b'{"type": "capture", "project_id": "%s", "provider": 5, "model": "m", "text": "x"}' % PID.encode(),
        b'{"type": "capture", "project_id": "%s", "provider": "openai", "model": "m", "text": 5}' % PID.encode(),
        b'{"type": "capture", "project_id": "%s", "provider": "openai", "model": "m"}' % PID.encode(),
        b'{"type": "baseline", "action": "delete-everything", "project_id": "%s"}' % PID.encode(),
        b'{"type": "hello", "pid": "abc"}',
        b'{"type": "heartbeat", "pid": 1, "stats": {"a": "not a number"}}',
        b'{"type": "heartbeat", "pid": 1, "stats": [1]}',
        b"\xff\xfe\x00",
    ],
)
def test_invalid_messages_get_an_error_reply_and_never_reach_the_handler(server, home, bad):
    srv, seen = server
    conn = raw_connect(home)
    reply = roundtrip(conn, bad)
    assert reply["ok"] is False and isinstance(reply["error"], str)
    assert seen == []
    assert roundtrip(conn, b'{"type": "status"}') == {"ok": True, "echo": "status"}  # still usable
    conn.close()


def test_a_pickle_payload_executes_nothing(server, home, tmp_path):
    marker = tmp_path / "pwned"

    class Evil:
        def __reduce__(self):
            return (Path(str(marker)).write_text, ("owned",))

    srv, seen = server
    conn = raw_connect(home)
    reply = roundtrip(conn, pickle.dumps(Evil()))
    assert reply["ok"] is False
    assert not marker.exists() and seen == []
    conn.close()


def test_a_wrong_key_is_rejected_and_the_server_keeps_serving(server, home):
    srv, seen = server
    conn = Client(ipc.address_for(home), family=ipc.FAMILY)
    nonce = conn.recv_bytes(maxlength=64)[3:]
    conn.send_bytes(hmac.new(b"wrong key", nonce, hashlib.sha256).digest())
    assert conn.recv_bytes(maxlength=8) == b"NO"
    with pytest.raises((EOFError, OSError)):
        conn.send_bytes(b'{"type": "status"}')
        conn.poll(2)
        conn.recv_bytes()
    assert seen == []
    assert ipc.IpcClient(home).send({"type": "status"}) == {"ok": True, "echo": "status"}


def test_an_oversized_message_drops_the_connection_without_hurting_the_server(server, home):
    srv, seen = server
    conn = raw_connect(home)
    dropped = False
    try:  # depending on the platform the drop shows up while sending or while reading the reply
        conn.send_bytes(b"x" * (ipc.MAX_MESSAGE + 10))
        assert conn.poll(3)
        conn.recv_bytes()
    except (EOFError, OSError):
        dropped = True
    assert dropped
    assert seen == []
    assert ipc.IpcClient(home).send({"type": "status"})["ok"] is True


def test_a_silent_client_cannot_block_others_or_shutdown(home):
    srv = ipc.IpcServer(home, lambda m: {"ok": True}, handshake_timeout=0.5)
    srv.start()
    silent = Client(ipc.address_for(home), family=ipc.FAMILY)  # connects, never answers the challenge
    start = time.monotonic()
    assert ipc.IpcClient(home).send({"type": "status"}) == {"ok": True}
    assert time.monotonic() - start < 2.0
    started = time.monotonic()
    srv.stop()
    assert time.monotonic() - started < 3.0
    silent.close()


def test_the_client_returns_quickly_when_no_agent_is_running(home):
    client = ipc.IpcClient(home)
    start = time.monotonic()
    for _ in range(5):
        assert client.send({"type": "heartbeat", "pid": 1}) is None
    assert (time.monotonic() - start) / 5 < 0.05
    assert client.last_error == "unavailable"


def test_the_client_reports_a_key_mismatch_as_auth(server, home, tmp_path):
    other = ipc.IpcClient(home)
    other._authkey = b"definitely not the key"
    assert other.send({"type": "status"}) is None
    assert other.last_error == "auth"


def test_addresses_are_per_home_and_the_key_is_stable_and_private(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    assert ipc.address_for(a) == ipc.address_for(a) and ipc.address_for(a) != ipc.address_for(b)
    k1 = ipc.load_or_create_authkey(a)
    assert k1 == ipc.load_or_create_authkey(a) and len(k1) >= 32
    assert ipc.load_or_create_authkey(b) != k1
    if POSIX:
        assert (os.stat(a / "agent" / "agent.key").st_mode & 0o777) == 0o600
        assert (os.stat(a / "agent").st_mode & 0o777) == 0o700


def test_concurrent_key_creation_agrees_on_one_key(tmp_path):
    keys = []
    barrier = threading.Barrier(8)

    def work():
        barrier.wait()
        keys.append(ipc.load_or_create_authkey(tmp_path / "race"))

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(keys) == 8 and len(set(keys)) == 1


def test_the_agent_code_never_uses_the_pickle_paths_of_multiprocessing_connections():
    root = Path(ipc.__file__).resolve().parent.parent
    offenders = []
    for path in list((root / "agent").glob("*.py")) + list((root / "capture").glob("*.py")) + [root / "autostart.py"]:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        # Connection.send / Connection.recv pickle. IpcClient.send is our own JSON method and is fine.
        for m in re.finditer(r"\.recv\(|\w*conn\w*\.send\(", text):
            offenders.append(f"{path.name}: {m.group(0)}")
        if re.search(r"^\s*(import|from)\s+pickle\b", text, re.M):
            offenders.append(f"{path.name}: pickle")
    assert offenders == []
