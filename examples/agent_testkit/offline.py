"""Offline then online: events made while the internet is down must wait on disk and arrive, once each, afterwards.

Run it from your linked project folder (needs the hash or real embedder, no key, no cost):

    python agent_testkit/offline.py

It starts a fake DriftWatch cloud on this machine (fake_ingest_server.py), points a fresh agent at it, makes the
cloud "down", sends traffic, checks nothing was delivered but everything is queued, brings the cloud back and
checks every queued event arrives exactly once. It also checks that a revoked key parks the project instead of
losing events. Exit code 1 if anything FAILs. Uses the local agent state of this machine: it is wiped first.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

KIT = Path(__file__).resolve().parent
sys.path.insert(0, str(KIT))

import check_agent as ck  # noqa: E402
from fake_ingest_server import FakeIngest  # noqa: E402

PY = sys.executable


def wait_for(fn, timeout: float, every: float = 0.3):
    end = time.time() + timeout
    while time.time() < end:
        got = fn()
        if got:
            return got
        time.sleep(every)
    return None


def traffic(env: dict, n: int, family: str, delay: str = "0.02") -> int:
    return subprocess.run(
        [PY, "-m", "driftwatch_llm", "run", "--", PY, str(KIT / "traffic.py"), "--n", str(n), "--family", family, "--delay", delay],
        env=env, capture_output=True, text=True, timeout=300,
    ).returncode


def pending(st) -> int:
    return sum(p["pending"] for p in st["projects"].values()) if st else -1


def main() -> int:
    server = FakeIngest(mode="down").start()
    env = {
        **os.environ,
        **server.dev_env(),
        "DRIFTWATCH_API_KEY": "dw_" + "0" * 10 + "_" + "0" * 64,
        "DRIFTWATCH_AGENT_MIN_INTERVAL": "1",
        "DRIFTWATCH_AGENT_BASELINE_SIZE": "30",
        "DRIFTWATCH_AGENT_LINGER": "900",  # the agent must outlive the apps, or queued events wait for the next app run
    }
    os.environ.update(env)  # the checks below talk to the same agent, so they share the settings
    try:
        ck.stop_agent()
        ck.report("INFO", "fake cloud", f"{server.url}, currently DOWN")
        subprocess.run([PY, str(KIT / "check_agent.py"), "reset", "--yes"], env=env, capture_output=True, timeout=60)
        ck.check(ck.start_agent(), "agent starts, pointed at the fake cloud")
        wait = subprocess.run([PY, str(KIT / "check_agent.py"), "wait-embedder"], env=env, capture_output=True, text=True, timeout=700)
        ck.check(wait.returncode == 0, "the model is loaded")

        traffic(env, 30, "a")  # baseline
        traffic(env, 45, "b", "0.25")  # shifted traffic -> drift values while the cloud is down
        st = wait_for(lambda: (s := ck.get_status()) and pending(s) >= 2 and s, 40)
        ck.check(bool(st), "drift values are produced and queued while the cloud is down", f"pending {pending(st) if st else '?'}")
        ck.check(server.count() == 0, "nothing was delivered while the cloud was down", f"delivered {server.count()}")
        queued = pending(st) if st else 0

        server.mode = "unauth"
        st2 = wait_for(lambda: (s := ck.get_status()) and "auth_failed" in {p.get("parked") for p in s["projects"].values()} and s, 45)
        ck.check(bool(st2), "a revoked key parks the project instead of dropping events",
                 f"parked {[p.get('parked') for p in (st2 or {}).get('projects', {}).values()]}")
        ck.check(pending(st2) >= queued if st2 else False, "the queued events are still there", f"{pending(st2) if st2 else '?'} >= {queued}")

        server.mode = "ok"
        # A rejected key stays parked until there is a different key or the agent restarts; restart it, which also
        # proves the queue survives a restart.
        ck.check(ck.stop_agent(), "the agent stops")
        ck.check(ck.start_agent(), "a new agent starts and finds the queue on disk")
        arrived = wait_for(lambda: server.count() >= queued and server.count(), 90)
        ck.check(bool(arrived), "after the cloud is back, every queued event arrives", f"{server.count()} of at least {queued}")
        ids = [e["event_id"] for e in server.events]
        ck.check(len(ids) == len(set(ids)), "each event arrived exactly once", f"{len(ids)} events")
        ck.check(server.rejected == 0, "the cloud accepted every event as valid", f"rejected {server.rejected}")
        done = wait_for(lambda: (s := ck.get_status()) and pending(s) == 0 and s, 30)
        ck.check(bool(done), "the local queue is empty at the end")
    finally:
        server.stop()
        ck.stop_agent()
    print(f"\n{'ALL GOOD' if ck.failures == 0 else str(ck.failures) + ' FAILED'}")
    return 1 if ck.failures else 0


if __name__ == "__main__":
    sys.exit(main())
