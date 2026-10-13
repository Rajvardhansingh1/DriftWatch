"""Print the agent's drift values over time as a table, so you can see by eye where traffic changed.

    python agent_testkit/compare_windows.py              # this folder's project
    python agent_testkit/compare_windows.py --last 60    # only the last 60 values

Reads the agent's local store (numbers only: no response text is ever stored). Bars are scaled 0..0.5.
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_agent as ck  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--last", type=int, default=100)
    args = ap.parse_args()
    pid = ck.project_id()
    if pid is None:
        print("This folder is not a linked project. Run `driftwatch init` first.")
        return 1
    from driftwatch_llm.agent import ipc
    from driftwatch_llm.agent.store import AgentStore

    db = ipc.agent_dir() / "agent.sqlite3"
    if not db.exists():
        print("The agent has not stored anything yet.")
        return 1
    store = AgentStore(db)
    try:
        rows = sorted(store.recent_signals(pid, "embedding_drift", args.last), key=lambda r: r["ts"])
    finally:
        store.close()
    if not rows:
        print("No drift values yet: the baseline may still be collecting (`driftwatch baseline status`).")
        return 0
    print(f"{'time':<9} {'drift':>6}  window  chart")
    for r in rows:
        meta = r.get("meta") or {}
        bar = "#" * min(40, int(r["value"] / 0.5 * 40))
        full = "" if meta.get("window_full", True) else " (early)"
        print(f"{datetime.fromtimestamp(r['ts']).strftime('%H:%M:%S'):<9} {r['value']:>6.3f}  {meta.get('current_n', '?'):>6}  {bar}{full}")
    values = [r["value"] for r in rows]
    half = len(values) // 2 or 1
    print(f"\nfirst half mean {sum(values[:half]) / half:.3f}, second half mean {sum(values[half:]) / max(1, len(values) - half):.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
