"""Measure what the embedding-drift signal alone can do (Plan 4, Task 10).

Drives the real agent Engine with the real MiniLM embedder over the project's offline scenarios (the simulated
LLM client, no API calls, no keys) and reports:

- the noise floor of the signal on stable traffic, by window size;
- for a sweep of thresholds: false-positive rate on stable traffic, and detection latency (in responses after
  onset) for model-downgrade, injection-creep and distribution-shift.

Honest limit: the simulated client produces only a handful of distinct sentences, so absolute numbers are a
benchmark of the detector on these scenarios, not a prediction for real traffic. Use it to compare window sizes
and thresholds, not to promise detection rates.

    python scripts/measure_embedding_only.py [--out-dir eval_reports] [--repeats 5]
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from demo_bot import scenarios  # noqa: E402
from demo_bot.bot import QABot  # noqa: E402
from demo_bot.simulated_client import SimulatedLLMClient  # noqa: E402
from driftwatch_llm.agent.engine import Engine  # noqa: E402
from driftwatch_llm.agent.store import AgentStore  # noqa: E402
from driftwatch_llm.core.embedding import make_embedder  # noqa: E402

PROJECT = "11111111-1111-4111-8111-111111111111"
QUERIES = [
    "What is the capital of France?",
    "What is the capital of Japan?",
    "What is 12 + 7?",
    "At sea level, what temperature in Celsius does water boil at?",
    "What is the largest planet in our solar system?",
]
BASELINE_N = 200
STABLE_N = 100
DEGRADED_N = 60
THRESHOLDS = [0.05, 0.10, 0.17, 0.25, 0.35, 0.50, 0.75]
SCENARIOS = {
    "model-downgrade": (scenarios.simulate_model_downgrade, scenarios.reset_model_downgrade),
    "injection-creep": (scenarios.simulate_injection_creep, scenarios.reset_injection_creep),
    "distribution-shift": (scenarios.simulate_distribution_shift, scenarios.reset_distribution_shift),
}


class CachingEmbedder:
    """The simulated client repeats sentences; embed each distinct one once."""

    def __init__(self, inner):
        self._inner = inner
        self._cache: dict[str, np.ndarray] = {}

    def encode(self, texts):
        out = []
        for t in texts:
            if t not in self._cache:
                self._cache[t] = np.asarray(self._inner.encode([t]))[0]
            out.append(self._cache[t])
        return np.stack(out)


class Clock:
    def __init__(self):
        # Start in the past: the run advances the clock about 35 minutes, and the event contract rejects
        # timestamps more than 5 minutes in the future.
        self.now = datetime.now(timezone.utc).timestamp() - 3600

    def __call__(self):
        return self.now


def traffic(bot: QABot, n: int, rng: random.Random, start: int = 0):
    for i in range(start, start + n):
        query = scenarios.next_query(bot, rng.choice(QUERIES), i)
        yield bot.ask(query, temperature=0.7).text


def run_once(embedder, scenario: str | None, seed: int) -> list[tuple[int, int, float]]:
    """Returns (responses_since_onset, window_size, drift_value) for every emission after the baseline."""
    rng = random.Random(seed)
    client = SimulatedLLMClient()
    for _ in range(seed * 7):  # shift the client's internal sampling sequence
        client.complete("s", "q", "m", 0.7)
    bot = QABot(client=client)
    clock = Clock()
    with tempfile.TemporaryDirectory() as tmp:
        store = AgentStore(Path(tmp) / "a.sqlite3", clock=clock)
        engine = Engine(store, embedder, clock=clock, baseline_size=BASELINE_N)
        for text in traffic(bot, BASELINE_N, rng):
            engine.capture(PROJECT, text)
        assert engine.baseline_status(PROJECT)["frozen"]
        points: list[tuple[int, int, float]] = []
        seen = 0

        def feed(texts, base_index):
            nonlocal seen
            for k, text in enumerate(texts, start=1):
                clock.now += 13  # five responses a minute apart: one emission per five responses
                for event in engine.capture(PROJECT, text):
                    if event["signal"] == "embedding_drift":
                        points.append((base_index + k, event["meta"]["current_n"], event["value"]))

        feed(list(traffic(bot, STABLE_N, rng, start=BASELINE_N)), -STABLE_N)  # negative index = before onset
        if scenario:
            activate, _reset = SCENARIOS[scenario]
            activate(bot)
        feed(list(traffic(bot, DEGRADED_N, rng, start=BASELINE_N + STABLE_N)), 0)
        store.close()
        return points


def pct(values, q):
    return float(np.percentile(values, q)) if values else float("nan")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out-dir", default="eval_reports")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--embedder", default="sentence-transformers", help='"onnx" uses fastembed (the agent default)')
    args = parser.parse_args()

    embedder = CachingEmbedder(make_embedder(args.embedder))
    report: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "embedder": args.embedder,
        "baseline_n": BASELINE_N,
        "repeats": args.repeats,
        "note": "Simulated traffic with few distinct sentences: compares window sizes and thresholds; "
        "it does not predict real-traffic detection rates.",
    }

    stable_runs = [run_once(embedder, None, seed) for seed in range(1, args.repeats + 1)]
    by_window: dict[int, list[float]] = {}
    for run in stable_runs:
        for _idx, w, v in run:  # stable traffic the whole way: every emission counts
            by_window.setdefault(w, []).append(v)
    report["stable_floor_by_window"] = {
        str(w): {"n": len(v), "mean": statistics.fmean(v), "p95": pct(v, 95), "max": max(v)}
        for w, v in sorted(by_window.items())
    }

    scenario_runs = {
        name: [run_once(embedder, name, seed) for seed in range(1, args.repeats + 1)] for name in SCENARIOS
    }

    def fp_rate(threshold: float, min_window: int) -> float:
        vals = [v for w, vs in by_window.items() if w >= min_window for v in vs]
        return sum(1 for v in vals if v > threshold) / len(vals) if vals else float("nan")

    rows = []
    for t in THRESHOLDS:
        row = {"threshold": t, "false_positive_rate_all_windows": fp_rate(t, 0), "false_positive_rate_window_ge_10": fp_rate(t, 10)}
        for name, runs in scenario_runs.items():
            latencies = []
            for run in runs:
                after = [(idx, v) for idx, _w, v in run if idx > 0 and v > t]
                latencies.append(min(after)[0] if after else None)
            hits = [x for x in latencies if x is not None]
            row[name] = {
                "detected_in": f"{len(hits)}/{len(latencies)} runs",
                "median_responses_to_detect": statistics.median(hits) if hits else None,
            }
        rows.append(row)
    report["threshold_sweep"] = rows
    report["late_scenario_values"] = {
        name: {"mean_of_last_5_emissions": statistics.fmean([statistics.fmean([v for _i, _w, v in run[-5:]]) for run in runs])}
        for name, runs in scenario_runs.items()
    }

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_embedding_only.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"embedder={args.embedder} baseline={BASELINE_N} repeats={args.repeats}\n")
    print("Stable-traffic noise floor of embedding_drift by window size:")
    print(f"{'window':>7} {'n':>5} {'mean':>8} {'p95':>8} {'max':>8}")
    for w, d in report["stable_floor_by_window"].items():
        print(f"{w:>7} {d['n']:>5} {d['mean']:>8.3f} {d['p95']:>8.3f} {d['max']:>8.3f}")
    print("\nThreshold sweep (responses after onset to first value above the threshold):")
    print(f"{'T':>6} {'FP all':>7} {'FP w>=10':>9} " + " ".join(f"{n:>22}" for n in SCENARIOS))
    for r in rows:
        cells = []
        for n in SCENARIOS:
            d = r[n]
            cells.append(f"{d['detected_in']} @{d['median_responses_to_detect']}".rjust(22))
        print(f"{r['threshold']:>6.2f} {r['false_positive_rate_all_windows']:>7.2f} {r['false_positive_rate_window_ge_10']:>9.2f} " + " ".join(cells))
    print("\nMean embedding_drift late in each scenario:", {k: round(v["mean_of_last_5_emissions"], 3) for k, v in report["late_scenario_values"].items()})
    print(f"\nreport: {path}")


if __name__ == "__main__":
    main()
