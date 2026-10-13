"""DEV-ONLY helper for e2e/run-local.mjs: a real agent runtime (hash embedder, no network) with some drift history,
serving the real local dashboard. Prints one JSON line {"port", "token"}, then runs until its stdin closes.

    python e2e/local_dashboard_demo.py <static_dir>
"""

import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from driftwatch_llm.agent import dashboard as dash  # noqa: E402
from driftwatch_llm.agent.runtime import AgentRuntime  # noqa: E402
from driftwatch_llm.core.embedding import make_embedder  # noqa: E402

PID = "11111111-2222-4333-8444-555555555555"
A = [f"Your invoice for the {p} plan renews on the {d} and the payment is {n} dollars." for p in ("Team", "Pro", "Basic") for d in ("5th", "10th") for n in (19, 49, 99)]
B = [f"Roast the {v} at {t} degrees for {m} minutes and finish with salt and lemon." for v in ("carrots", "onions", "peppers") for t in (180, 200) for m in (10, 20, 30)]


def main() -> None:
    static = Path(sys.argv[1])
    home = Path(tempfile.mkdtemp(prefix="dw_e2e_"))
    now = [time.time() - 3600.0]
    rt = AgentRuntime(
        home=home, embedder_factory=lambda: make_embedder("hash"), clock=lambda: now[0],
        baseline_size=30, min_baseline=30, min_interval=0.1, linger=3600.0, sync_interval=3600.0,
    )
    rt.load_embedder_now()
    for i in range(30):
        rt.handle({"type": "capture", "project_id": PID, "provider": "openai", "model": "m", "text": A[i % len(A)] + f" #{i}"})
    rt.drain()
    for i in range(60):
        text = (A if i < 25 else B)[i % 18] + f" #{i}"
        now[0] += 30.0
        rt.handle({"type": "capture", "project_id": PID, "provider": "openai", "model": "m", "text": text})
        rt.drain()
    rt._dashboard_start()
    rt._dashboard._static = static  # type: ignore[attr-defined]
    server = rt._dashboard
    print(json.dumps({"port": server.address[1], "token": server.token}), flush=True)
    sys.stdin.read()  # run until the harness closes our stdin
    rt.shutdown()


if __name__ == "__main__":
    main()
