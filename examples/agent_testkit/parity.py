"""Parity: what the local dashboard shows must equal what the cloud received.

    python agent_testkit/parity.py

Runs traffic through a fresh agent pointed at a fake cloud (fake_ingest_server.py), waits until every event has
synced, then reads the agent's local dashboard API and compares it with the cloud's rows, signal by signal.
Exit code 1 on any FAIL.
"""

import http.client
import json
import os
import subprocess
import sys
import time
from pathlib import Path

KIT = Path(__file__).resolve().parent
sys.path.insert(0, str(KIT))

import check_agent as ck  # noqa: E402
from fake_ingest_server import FakeIngest  # noqa: E402
from offline import traffic, wait_for  # noqa: E402

PY = sys.executable


def api(port: int, cookie: str, path: str):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", path, headers={"Cookie": cookie})
    r = conn.getresponse()
    body = r.read()
    conn.close()
    return r.status, json.loads(body)


def main() -> int:
    server = FakeIngest(mode="ok").start()
    env = {
        **os.environ,
        **server.dev_env(),
        "DRIFTWATCH_API_KEY": "dw_" + "1" * 10 + "_" + "1" * 64,
        "DRIFTWATCH_AGENT_MIN_INTERVAL": "1",
        "DRIFTWATCH_AGENT_BASELINE_SIZE": "30",
        "DRIFTWATCH_AGENT_LINGER": "900",
    }
    os.environ.update(env)
    try:
        ck.stop_agent()
        subprocess.run([PY, str(KIT / "check_agent.py"), "reset", "--yes"], env=env, capture_output=True, timeout=60)
        ck.check(ck.start_agent(), "agent starts, pointed at the fake cloud")
        wait = subprocess.run([PY, str(KIT / "check_agent.py"), "wait-embedder"], env=env, capture_output=True, text=True, timeout=700)
        ck.check(wait.returncode == 0, "the model is loaded")
        traffic(env, 30, "a")
        traffic(env, 40, "b", "0.25")
        from driftwatch_llm.agent import ipc

        def synced():
            s = ck.get_status()
            return s and s["queued"] == 0 and sum(p["pending"] for p in s["projects"].values()) == 0 and server.count() >= 2 and s

        ck.check(bool(wait_for(synced, 90)), "every event reached the cloud", f"{server.count()} events")
        reply = ipc.IpcClient(io_timeout=15.0).send({"type": "dashboard"})
        ck.check(bool(reply and reply.get("ok")), "the agent starts its dashboard")
        port, token = reply["port"], reply["token"]
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("POST", "/session", json.dumps({"token": token}), {"Content-Type": "application/json"})
        r = conn.getresponse()
        r.read()
        cookie = r.getheader("Set-Cookie", "").split(";")[0]
        conn.close()
        ck.check(r.status == 204 and cookie.startswith("dw_session="), "the page can sign in with the token")
        pid = ck.project_id()
        status, series = api(port, cookie, f"/api/series?project={pid}&range=24h")
        ck.check(status == 200, "the local API answers")
        for signal in ("embedding_drift", "combined_score"):
            local = [(p["timestamp"], round(p["value"], 9)) for p in series[signal]]
            cloud = sorted((e["occurred_at"], round(e["value"], 9)) for e in server.events if e["signal"] == signal)
            ck.check(len(cloud) > 0 and local == cloud,
                     f"{signal}: the local chart equals what the cloud stored", f"{len(local)} local, {len(cloud)} cloud")
        status, st = api(port, cookie, "/api/status")
        ck.check(st["sync"]["state"] == "synced" and st["sync"]["pending"] == 0, "the sync chip says synced", json.dumps(st["sync"]["state"]))
    finally:
        server.stop()
        ck.stop_agent()
    print(f"\n{'ALL GOOD' if ck.failures == 0 else str(ck.failures) + ' FAILED'}")
    return 1 if ck.failures else 0


if __name__ == "__main__":
    sys.exit(main())
