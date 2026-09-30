"""Synthetic degradation evaluation (spec §7 / Phase 7).

Injects known, LABELED degradations into a controlled run and measures
whether DriftWatch's live detector — the exact same monitor/pipeline.py
code path the FastAPI service uses — catches them. The labels (which
scenario is active, at which query it started) are used ONLY by this
script to score detection; they are never passed into the detector
itself, which only ever sees bot.ask() responses like production traffic.

Usage:
    python scripts/run_detection_eval.py [--out-dir eval_reports]
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from demo_bot import scenarios  # noqa: E402
from demo_bot.bot import QABot  # noqa: E402
from demo_bot.simulated_client import SimulatedLLMClient  # noqa: E402
from monitor.db.session import get_session, init_db  # noqa: E402
from monitor.pipeline import PipelineState, run_query_cycle  # noqa: E402
from monitor.signals.canary_probes import CanaryCache, load_probes  # noqa: E402
from monitor.signals.scheduler import run_canary_job  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CANARY_PROBES_PATH = DATA_DIR / "canary_probes.yaml"

BASELINE_QUERIES = [
    "What is the capital of France?",
    "What is the capital of Japan?",
    "What is 12 + 7?",
    "At sea level, what temperature in Celsius does water boil at?",
    "What is the largest planet in our solar system?",
]

WARMUP_QUERIES = 8
DEGRADED_QUERIES = 25
STABLE_RUN_QUERIES = 30

SCENARIOS = {
    "model-downgrade": (scenarios.simulate_model_downgrade, scenarios.reset_model_downgrade),
    "injection-creep": (scenarios.simulate_injection_creep, scenarios.reset_injection_creep),
    "distribution-shift": (
        scenarios.simulate_distribution_shift,
        scenarios.reset_distribution_shift,
    ),
}


def _fresh_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    init_db(engine=engine)
    return get_session(engine=engine)


def _fresh_pipeline() -> tuple[PipelineState, object]:
    client = SimulatedLLMClient()
    bot = QABot(client=client)
    baseline = [QABot(client=client).ask(q, temperature=0.0).text for q in BASELINE_QUERIES]
    return PipelineState(bot=bot, judge_client=client, baseline_texts=baseline), client


@dataclass
class ScenarioResult:
    scenario: str
    detected: bool
    detection_latency_queries: int | None
    triggering_signals_at_detection: list[str]
    final_score: float


def run_scenario_eval(name: str) -> ScenarioResult:
    activate, reset = SCENARIOS[name]
    state, _client = _fresh_pipeline()
    session = _fresh_session()
    probes = load_probes(str(CANARY_PROBES_PATH))
    canary_cache = CanaryCache()

    for i in range(WARMUP_QUERIES):
        run_query_cycle(state, session, query_text=BASELINE_QUERIES[i % len(BASELINE_QUERIES)])
    run_canary_job(state.bot, probes, lambda: session, canary_cache)

    activate(state.bot)
    # Mirrors monitor/main.py's scenario endpoint, which re-runs canary
    # immediately on activation — without this, canary_accuracy (the
    # signal spec §5 names as model-downgrade's primary indicator) never
    # gets a data point during this run and is silently excluded from
    # the combined score.
    run_canary_job(state.bot, probes, lambda: session, canary_cache)

    detected_at: int | None = None
    triggering: list[str] = []
    last_result: dict = {}
    for i in range(1, DEGRADED_QUERIES + 1):
        result = run_query_cycle(state, session, query_text=None)
        last_result = result
        if detected_at is None and result["alert"]:
            detected_at = i
            triggering = result["triggering_signals"]

    reset(state.bot)

    return ScenarioResult(
        scenario=name,
        detected=detected_at is not None,
        detection_latency_queries=detected_at,
        triggering_signals_at_detection=triggering or last_result.get("triggering_signals", []),
        final_score=last_result.get("score", 0.0),
    )


def run_false_positive_eval() -> dict:
    state, _client = _fresh_pipeline()
    session = _fresh_session()
    alerts = 0
    for i in range(STABLE_RUN_QUERIES):
        result = run_query_cycle(state, session, query_text=BASELINE_QUERIES[i % len(BASELINE_QUERIES)])
        if result["alert"]:
            alerts += 1
    return {
        "queries_run": STABLE_RUN_QUERIES,
        "false_positives": alerts,
        "false_positive_rate": alerts / STABLE_RUN_QUERIES,
    }


def run_canary_baseline() -> dict:
    client = SimulatedLLMClient()
    bot = QABot(client=client)
    probes = load_probes(str(CANARY_PROBES_PATH))
    session = _fresh_session()
    result = run_canary_job(bot, probes, lambda: session, CanaryCache())
    return {"n_probes": len(probes), "accuracy": result["accuracy"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default="eval_reports")
    args = parser.parse_args()

    scenario_results = [run_scenario_eval(name) for name in SCENARIOS]
    false_positive = run_false_positive_eval()
    canary_baseline = run_canary_baseline()

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": (
            "Synthetic labels were used only to score detection here; the "
            "live detector never receives labels (spec cross-phase invariant)."
        ),
        "detection_latency": [asdict(r) for r in scenario_results],
        "false_positive_rate": false_positive,
        "canary_accuracy_baseline": canary_baseline,
    }

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"{stamp}_detection_eval.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Wrote {out_path}")
    print()
    for r in scenario_results:
        status = f"detected after {r.detection_latency_queries} queries" if r.detected else "NOT detected"
        print(f"  {r.scenario}: {status} — triggering: {r.triggering_signals_at_detection}")
    print(
        f"  stable traffic false-positive rate: "
        f"{false_positive['false_positives']}/{false_positive['queries_run']} "
        f"({false_positive['false_positive_rate']:.1%})"
    )
    print(f"  canary accuracy baseline: {canary_baseline['accuracy']:.2f}")


if __name__ == "__main__":
    main()
