"""Core per-query signal pipeline, shared by the live FastAPI service
(monitor/main.py) and the offline evaluation harness
(scripts/run_detection_eval.py) so detection behavior is identical in
both — the evaluation must measure the real detector, not a reimplementation
of it."""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from demo_bot import scenarios
from demo_bot.bot import QABot
from monitor.ingest import record_embedding_drift, record_self_consistency
from monitor.scoring.combined_score import compute_combined_score
from monitor.signals.hallucination_signal import record_hallucination_score
from monitor.signals.judge_trend import record_judge_score

CURRENT_WINDOW_MAXLEN = 20
SELF_CONSISTENCY_SAMPLES = 3
JUDGE_SAMPLE_EVERY_N_QUERIES = 4


@dataclass
class PipelineState:
    bot: QABot
    judge_client: object
    baseline_texts: list[str]
    current_window: list[str] = field(default_factory=list)
    query_count: int = 0
    rate_limiter: object | None = None


def run_query_cycle(state: PipelineState, session: Session, query_text: str | None = None) -> dict:
    state.query_count += 1
    cycle_index = state.query_count

    if query_text is None:
        query_text = scenarios.next_query(state.bot, "Tell me something interesting.", cycle_index)

    primary = state.bot.ask(query_text, temperature=0.0)
    llm_calls = 1

    samples = []
    for _ in range(SELF_CONSISTENCY_SAMPLES):
        samples.append(state.bot.ask(query_text, temperature=0.7).text)
        llm_calls += 1

    window = state.current_window
    window.append(primary.text)
    if len(window) > CURRENT_WINDOW_MAXLEN:
        del window[: len(window) - CURRENT_WINDOW_MAXLEN]

    if state.baseline_texts and len(window) >= 5:
        record_embedding_drift(session, state.baseline_texts, window)

    if samples:
        record_self_consistency(session, query_text, samples)
        record_hallucination_score(session, primary.text, samples=samples)

    judge_sampled = cycle_index % JUDGE_SAMPLE_EVERY_N_QUERIES == 0
    if judge_sampled:
        record_judge_score(
            session, state.judge_client, query_text, primary.text, rate_limiter=state.rate_limiter
        )
        llm_calls += 1

    result = compute_combined_score(session)
    return {
        "query": query_text,
        "response": primary.text,
        "model_id": primary.model_id,
        "score": result.score,
        "alert": result.alert,
        "triggering_signals": result.triggering_signals,
        "contributions": result.contributions,
        "llm_calls": llm_calls,
    }
