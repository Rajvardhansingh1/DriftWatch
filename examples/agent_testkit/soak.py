"""A long, steady run: the agent must not leak memory, lose events or fall over.

    python -m driftwatch_llm run -- python agent_testkit/soak.py --minutes 30
    (or with autostart on:)        python agent_testkit/soak.py --minutes 30

Makes a call every --every seconds (stable billing text, with a shift to cooking text for the last fifth), and
every minute samples the agent: memory (needs `pip install psutil`; skipped otherwise), queue length, counters.
At the end it prints a table and checks: memory did not keep growing, the agent never stopped answering, and
nothing was dropped. Exit code 1 on any FAIL. 30 minutes is a good first soak; run it for hours before a release.
"""

import argparse
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "fake_sdk"))

import check_agent as ck  # noqa: E402
import corpus  # noqa: E402


def rss_mb(pid: int):
    try:
        import psutil

        return psutil.Process(pid).memory_info().rss / 1e6
    except Exception:  # noqa: BLE001 - psutil missing or the process is gone
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--minutes", type=float, default=30.0)
    ap.add_argument("--every", type=float, default=1.0, help="seconds between calls")
    args = ap.parse_args()

    import openai.resources.chat.completions as c  # the fake SDK (or the real one, if installed and patched)

    rng = random.Random(7)
    state = {"family": "a"}
    c.Completions.responder = lambda messages: corpus.make_response(state["family"], rng)
    sdk = c.Completions()

    def call() -> None:
        sdk.create(model="soak", messages=[{"role": "user", "content": corpus.make_prompt(state["family"], rng)}])

    call()  # the first call starts the capture client
    try:
        from driftwatch_llm.capture import wrappers

        client = getattr(wrappers._sink, "__self__", None)
    except Exception:  # noqa: BLE001
        client = None
    ck.check(client is not None, "monitoring is active in this process (run via `driftwatch run --` or autostart)")
    if client is None:
        return 1

    end = time.time() + args.minutes * 60
    shift_at = time.time() + args.minutes * 60 * 0.8
    next_sample = time.time() + 60
    samples = []
    calls = 0
    while time.time() < end:
        state["family"] = "b" if time.time() >= shift_at else "a"
        try:
            call()
            calls += 1
        except Exception as exc:  # noqa: BLE001
            ck.report("INFO", "call failed", type(exc).__name__)
        if time.time() >= next_sample:
            next_sample += 60
            st = ck.get_status(10.0)
            if st is None:
                ck.report("FAIL", "the agent stopped answering", f"after {calls} calls")
                break
            samples.append((calls, st["pid"], rss_mb(st["pid"]), st.get("queued", 0), st["counters"]))
            print(f"  t+{len(samples)}m calls {calls} rss {samples[-1][2] and round(samples[-1][2])} MB queued {samples[-1][3]}", flush=True)
        time.sleep(args.every)

    if len(samples) >= 4:
        mems = [m for _c, _p, m, _q, _k in samples if m is not None]
        if len(mems) >= 4:
            third = max(1, len(mems) // 3)
            early, late = sum(mems[:third]) / third, sum(mems[-third:]) / third
            ck.check(late < early * 1.5 + 20, "memory stayed flat", f"{early:.0f} MB early, {late:.0f} MB late")
        else:
            ck.report("INFO", "memory", "not tracked (pip install psutil to enable)")
        pids = {p for _c, p, _m, _q, _k in samples}
        ck.check(len(pids) == 1, "one agent process the whole time", f"pids {sorted(pids)}")
    last = samples[-1][4] if samples else {}
    ck.check(last.get("dropped_queue_full", 0) == 0 and last.get("capture_errors", 0) == 0, "nothing dropped, no errors",
             f"dropped {last.get('dropped_queue_full', 0)}, errors {last.get('capture_errors', 0)}")
    return 1 if ck.failures else 0


if __name__ == "__main__":
    sys.exit(main())
