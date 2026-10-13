"""Runs the whole DriftWatch agent test sequence and prints one summary. Run it from your linked project folder:

    cd D:\\Work.ext\\AIProjects\\TestingDW
    python agent_testkit\\run_all.py                 # about 3 minutes, no API key, no cost (fake SDK)
    python agent_testkit\\run_all.py --quick         # about 1 minute, smaller phases
    python agent_testkit\\run_all.py --sdk groq --model <a-cheap-model>    # real provider, about 150 calls

What it does, in order:
  1. wipes the LOCAL agent state (not your key, not your project link), starts a fresh agent, waits for the model
  2. baseline traffic (billing text), then stable traffic -> checks counters, baseline, privacy, security
  3. shifted traffic (cooking text) -> the drift score must clearly rise
  4. 20 simultaneous starts, then a hard kill -> the agent must recover with its baseline and history intact

It sets DRIFTWATCH_AGENT_MIN_INTERVAL=2 so drift values appear every few seconds instead of once a minute.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

KIT = Path(__file__).resolve().parent
PY = sys.executable
LINE = re.compile(r"^(PASS|FAIL|INFO)\s+(.*)$")


def run(title: str, cmd: list[str], env: dict) -> tuple[int, list[str]]:
    print(f"\n=== {title}", flush=True)
    proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    lines = []
    for line in proc.stdout:
        line = line.rstrip("\n")
        print("   " + line, flush=True)
        lines.append(line)
    return proc.wait(), lines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quick", action="store_true", help="smaller phases")
    ap.add_argument("--sdk", choices=["fake", "groq", "openai"], default="fake")
    ap.add_argument("--model", help="needed with --sdk groq/openai")
    ap.add_argument("--baseline", type=int, default=None, help="baseline size (min 30). Default 200, quick 60, real 40")
    ap.add_argument("--keep-state", action="store_true", help="do not wipe the local agent state first")
    args = ap.parse_args()

    real = args.sdk != "fake"
    if real and not args.model:
        print("--model is required with a real provider")
        return 2
    baseline = args.baseline or (40 if real else 60 if args.quick else 200)
    if baseline < 30:
        print("--baseline must be at least 30")
        return 2
    stable_n = 40 if (args.quick or real) else 60  # enough paced responses for >= 3 full-window drift values
    shift_n = 30 if (args.quick or real) else 60
    delay = "0.5" if not real else "0.2"

    env = {**os.environ, "DRIFTWATCH_AGENT_MIN_INTERVAL": "2", "DRIFTWATCH_AGENT_BASELINE_SIZE": str(baseline)}
    marker = f"TESTKIT-MARKER-{uuid.uuid4().hex[:10]}"
    check = [PY, str(KIT / "check_agent.py")]
    sdk_args = ["--sdk", args.sdk] + (["--model", args.model] if args.model else [])

    # -- preflight
    print("=== preflight")
    try:
        import driftwatch_llm  # noqa: F401
        print(f"   driftwatch-llm {driftwatch_llm.__version__}")
    except ImportError:
        print("   driftwatch-llm is not installed in this Python. Activate your venv first.")
        return 2
    if not env.get("DRIFTWATCH_AGENT_EMBEDDER"):
        try:
            import fastembed, numpy  # noqa: F401,E401
        except ImportError:
            print('   the agent extra is missing. Run: pip install "driftwatch-llm[agent]"')
            return 2
    rc, out = run("project", [PY, "-m", "driftwatch_llm", "status"], env)
    if not any(l.strip() == "trusted: yes" for l in out):
        print("\n   This folder is not a linked, trusted DriftWatch project. Run `driftwatch init` here first.")
        return 2

    results: list[tuple[str, str, str]] = []  # (step, kind, text)

    def step(title: str, cmd: list[str], expect_rc_zero: bool = True) -> None:
        rc, lines = run(title, cmd, env)
        for l in lines:
            m = LINE.match(l.strip())
            if m:
                results.append((title, m.group(1), m.group(2)))
        if expect_rc_zero and rc != 0 and not any(k == "FAIL" and t == title for t, k, _ in results):
            results.append((title, "FAIL", f"exited with code {rc}"))

    def traffic(title: str, n: int, family: str, delay_s: str) -> tuple[float, float]:
        t0 = time.time()
        step(title, [PY, "-m", "driftwatch_llm", "run", "--", PY, str(KIT / "traffic.py"), "--n", str(n),
                     "--family", family, "--delay", delay_s, "--marker", marker, *sdk_args])
        return t0, time.time()

    # -- 1. clean start
    if not args.keep_state:
        step("1. wipe local agent state", check + ["reset", "--yes"])
    step("2. start the agent and load the model", check + ["wait-embedder"])

    # -- 2. baseline + stable
    traffic(f"3. baseline traffic ({baseline} billing answers)", baseline, "a", "0.03" if not real else "0.2")
    t0, t1 = traffic(f"4. stable traffic ({stable_n} billing answers, paced)", stable_n, "a", delay)
    phases = {"stable": [t0, t1]}
    step("5. counters, baseline and sync", check + ["basics", "--expect", str(baseline + stable_n), "--baseline", str(baseline)])
    if real:
        results.append(("6. privacy", "INFO", "marker test skipped: a real provider's text cannot be tagged"))
    else:
        step("6. privacy: response text is never stored", check + ["privacy", "--marker", marker])
    step("7. security: attacks on the agent's own endpoint", check + ["security"])

    # -- 3. drift
    t0, t1 = traffic(f"8. shifted traffic ({shift_n} cooking answers)", shift_n, "b", delay)
    phases["shift"] = [t0, t1]
    phases_file = KIT / ".phases.json"
    phases_file.write_text(json.dumps(phases))
    step("9. drift: shifted traffic must score higher", check + ["drift", "--phases", str(phases_file)] + (["--margin", "0.1"] if env.get("DRIFTWATCH_AGENT_EMBEDDER") == "hash" else []))

    # -- 4. resilience
    step("10. resilience: simultaneous starts, then a hard kill", check + ["resilience"])

    # -- summary
    print("\n" + "=" * 78 + "\nSUMMARY")
    fails = 0
    current = None
    for title, kind, text in results:
        if title != current:
            print(f"\n{title}")
            current = title
        print(f"  {kind:<4} {text}")
        fails += kind == "FAIL"
    passes = sum(1 for _t, k, _x in results if k == "PASS")
    print("\n" + "=" * 78)
    print(f"{passes} passed, {fails} failed")
    if fails == 0:
        print("All good. The agent is monitoring correctly on this machine.")
    else:
        print("Something failed. Read the FAIL lines above; `python -m driftwatch_llm agent status` shows the agent's own view.")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
