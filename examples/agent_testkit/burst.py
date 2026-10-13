"""A burst: many responses in a short time, straight at the agent. Nothing may be lost silently and the agent
must keep answering.

    python agent_testkit/burst.py --n 2000 --threads 8

Sends --n capture messages over the agent's local endpoint from --threads threads, as fast as it can, then waits
for the agent's queue to drain. PASS needs: every message was answered, the agent stayed responsive while busy,
and captured + dropped (queue full) equals what was sent. Exit code 1 on any FAIL.
"""

import argparse
import random
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_agent as ck  # noqa: E402
from corpus import make_response  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--threads", type=int, default=8)
    args = ap.parse_args()

    pid = ck.project_id()
    if not ck.check(pid is not None, "this folder is a linked project"):
        return 1
    ck.check(ck.start_agent(), "agent starts")
    before = (ck.get_status() or {}).get("counters", {})
    from driftwatch_llm.agent import ipc

    answered = [0] * args.threads
    slowest = [0.0] * args.threads
    per = args.n // args.threads

    def worker(i: int) -> None:
        rng = random.Random(i)
        client = ipc.IpcClient()
        for k in range(per):
            t0 = time.perf_counter()
            reply = client.send({"type": "capture", "project_id": pid, "provider": "openai", "model": "burst",
                                 "text": make_response("a", rng), "latency_ms": 1.0})
            slowest[i] = max(slowest[i], time.perf_counter() - t0)
            answered[i] += bool(reply and reply.get("ok"))
        client.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(args.threads)]
    t0 = time.time()
    for t in threads:
        t.start()
    status_times = []
    while any(t.is_alive() for t in threads):  # is the agent still responsive while it is busy?
        s0 = time.perf_counter()
        ck.get_status(10.0)
        status_times.append(time.perf_counter() - s0)
        time.sleep(0.25)
    for t in threads:
        t.join()
    sent = per * args.threads
    took = time.time() - t0
    ck.report("INFO", "burst", f"{sent} messages in {took:.1f}s ({sent / took:.0f}/s), slowest answer {max(slowest) * 1000:.0f} ms")
    ck.check(sum(answered) == sent, "every message was answered", f"{sum(answered)} of {sent}")
    ck.check(not status_times or max(status_times) < 5.0, "the agent kept answering status requests while busy",
             f"slowest {max(status_times or [0]) * 1000:.0f} ms")
    st = ck.get_status() or {}
    deadline = time.time() + 120
    while time.time() < deadline and st.get("queued", 0) > 0:
        time.sleep(0.5)
        st = ck.get_status() or {}
    ck.check(st.get("queued", 1) == 0, "the agent worked through its queue", f"queued {st.get('queued')}")
    after = st.get("counters", {})
    d = lambda k: after.get(k, 0) - before.get(k, 0)  # noqa: E731
    ck.report("INFO", "counters", f"captured +{d('captured')}, dropped (queue full) +{d('dropped_queue_full')}, "
                                  f"errors +{d('capture_errors')}, dropped (no model) +{d('dropped_no_embedder')}")
    ck.check(d("captured") + d("dropped_queue_full") + d("dropped_no_embedder") >= sent,
             "nothing vanished: processed + counted drops cover everything sent",
             f"{d('captured')} + {d('dropped_queue_full')} + {d('dropped_no_embedder')} vs {sent}")
    return 1 if ck.failures else 0


if __name__ == "__main__":
    sys.exit(main())
