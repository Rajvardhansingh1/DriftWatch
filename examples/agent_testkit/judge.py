"""The opt-in judge, end to end: off by default, redacted when on, scores become a trend, and a spent allowance parks it.

    python agent_testkit/judge.py

Run from your linked project folder. Uses a fake cloud (fake_ingest_server.py) and a fake relay (fake_relay.py) on this
machine: no account, no key, no provider quota. It wipes the LOCAL agent state first, and leaves the judge OFF
(your own judge settings are restored at the end). Exit code 1 if anything FAILs.
"""

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
from fake_relay import FakeRelay  # noqa: E402
from offline import wait_for  # noqa: E402

PY = sys.executable
PLANT_EMAIL = "jane.doe@example.com"
PLANT_KEY = "sk-" + "Q1w2E3r4T5y6U7i8O9p0A1s2"


def traffic(env: dict, n: int, family: str, marker: str, delay: str = "0.05") -> int:
    return subprocess.run(
        [PY, "-m", "driftwatch_llm", "run", "--", PY, str(KIT / "traffic.py"), "--n", str(n), "--family", family,
         "--delay", delay, "--marker", marker],
        env=env, capture_output=True, text=True, timeout=300,
    ).returncode


def judge_state() -> str:
    st = ck.get_status()
    return (st or {}).get("judge", {}).get("state", "?")


def main() -> int:
    from driftwatch_llm import paths
    from driftwatch_llm.judge_settings import JudgeSettings, read_settings, write_settings

    ingest = FakeIngest(mode="ok").start()
    relay = FakeRelay(mode="ok", cap=50).start()
    env = {
        **os.environ,
        **ingest.dev_env(),
        **relay.dev_env(),
        "DRIFTWATCH_API_KEY": "dw_" + "2" * 10 + "_" + "2" * 64,
        "DRIFTWATCH_AGENT_MIN_INTERVAL": "1",
        "DRIFTWATCH_AGENT_BASELINE_SIZE": "30",
        "DRIFTWATCH_AGENT_LINGER": "900",
    }
    os.environ.update(env)
    home = paths.config_dir()
    saved = read_settings(home)
    marker = "TESTKIT-MARKER-judge77"
    planted = f"{marker} mail {PLANT_EMAIL} key {PLANT_KEY}"
    try:
        write_settings(home, JudgeSettings(enabled=False))
        ck.stop_agent()
        subprocess.run([PY, str(KIT / "check_agent.py"), "reset", "--yes"], env=env, capture_output=True, timeout=60)
        ck.check(ck.start_agent(), "agent starts, pointed at the fake cloud and the fake relay")
        wait = subprocess.run([PY, str(KIT / "check_agent.py"), "wait-embedder"], env=env, capture_output=True, text=True, timeout=700)
        ck.check(wait.returncode == 0, "the model is loaded")

        # 1. off by default
        traffic(env, 30, "a", planted)
        time.sleep(2)
        ck.check(len(relay.requests) == 0, "the judge is off by default: no request reached the relay", f"{len(relay.requests)} requests")
        ck.check(judge_state() == "off", "status says the judge is off", judge_state())

        # 2. on: sampled, redacted, only the documented fields
        write_settings(home, JudgeSettings(enabled=True, credential="free", sample_every=2, max_per_day=40))
        traffic(env, 40, "a", planted)
        got = wait_for(lambda: len(relay.requests) >= 10 and len(relay.requests), 60)
        ck.check(bool(got), "once on, about every second response is sent to the relay", f"{len(relay.requests)} requests")
        reqs = list(relay.requests)
        ck.check(all(r["key_ok"] for r in reqs), "every request carried a project key in the right shape")
        ck.check(all(r["fields"] == ["idempotency_key", "text"] for r in reqs), "the body has only text and idempotency_key")
        texts = [r["text"] or "" for r in reqs]
        ck.check(not any(PLANT_EMAIL in t or PLANT_KEY in t for t in texts), "the planted e-mail address and API key never reached the relay")
        ck.check(any("[email]" in t and "[secret]" in t for t in texts), "they were replaced by [email] and [secret]")
        ck.check(all(len(t) <= 1500 for t in texts), "every sample was cut to 1500 characters")

        # 3. scores become a trend, and the combined score uses it
        trend = wait_for(lambda: ingest.count("judge_trend") >= 1 and ingest.count("judge_trend"), 60)
        ck.check(bool(trend), "judge_trend events reach the cloud", f"{ingest.count('judge_trend')} events")
        traffic(env, 40, "b", planted, "0.25")
        both = wait_for(lambda: any(e["signal"] == "combined_score" and e["meta"].get("mode") == "embedding_judge" for e in ingest.events), 60)
        ck.check(bool(both), "the combined score now says embedding_judge")
        ck.check(any(e["signal"] == "judge_trend" and e["meta"].get("mode") == "judge_answer_only" and e["meta"].get("credential") == "free"
                     for e in ingest.events), "judge events say answer-only and which credential was used")

        # 4. privacy: the planted text is in no local file
        priv = subprocess.run([PY, str(KIT / "check_agent.py"), "privacy", "--marker", marker], env=env, capture_output=True, text=True, timeout=120)
        ck.check(priv.returncode == 0 and "FAIL" not in priv.stdout, "the planted text is in NO local file (the judge keeps text in memory only)")

        # 5. a spent allowance parks the judge; drift values keep flowing
        before = ingest.count("embedding_drift")
        relay.mode = "exhausted"
        traffic(env, 30, "b", planted)
        parked = wait_for(lambda: judge_state().startswith("parked: free allowance used") and judge_state(), 60)
        ck.check(bool(parked), "a spent allowance parks the judge with a plain sentence", judge_state()[:80])
        ck.check("driftwatch key set" in judge_state(), "the sentence says how to continue (add your own key)")
        traffic(env, 30, "b", planted)
        more = wait_for(lambda: ingest.count("embedding_drift") > before and ingest.count("embedding_drift"), 60)
        ck.check(bool(more), "embedding drift keeps flowing while the judge is parked")
        seen = len(relay.requests)
        traffic(env, 10, "b", planted)
        time.sleep(2)
        ck.check(len(relay.requests) == seen, "nothing more is sent while parked (no retry storm, no other credential)")
    finally:
        write_settings(home, saved)
        relay.stop()
        ingest.stop()
        ck.stop_agent()
    print(f"\n{'ALL GOOD' if ck.failures == 0 else str(ck.failures) + ' FAILED'}")
    return 1 if ck.failures else 0


if __name__ == "__main__":
    sys.exit(main())
