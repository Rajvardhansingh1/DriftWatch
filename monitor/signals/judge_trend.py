"""LLM-as-judge trend tracker: sparingly scores sampled live outputs
against a rubric and tracks the trend line over time, not any single
score (which cancels out normal judge noise)."""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from demo_bot.bot import STRONG_MODEL
from monitor.db.writer import read_signal_window, write_signal

RUBRIC_PROMPT_TEMPLATE = (
    "You are grading an AI assistant's answer on a 0-10 rubric for accuracy, "
    "relevance, and groundedness.\nQuery: {query}\nAnswer: {answer}\n"
    "Respond with only a single number from 0 to 10."
)
JUDGE_SYSTEM_PROMPT = "You are a strict, consistent grader. Output only a number."


def score_with_judge(
    judge_client, query: str, answer: str, model: str = STRONG_MODEL, rate_limiter=None
) -> float:
    if rate_limiter is not None:
        rate_limiter.consume()
    prompt = RUBRIC_PROMPT_TEMPLATE.format(query=query, answer=answer)
    raw = judge_client.complete(JUDGE_SYSTEM_PROMPT, prompt, model=model, temperature=0.0)
    match = re.search(r"\d+(\.\d+)?", raw)
    if not match:
        raise ValueError(f"judge did not return a parseable score: {raw!r}")
    score = float(match.group(0))
    return max(0.0, min(1.0, score / 10.0))


def record_judge_score(session: Session, judge_client, query: str, answer: str, rate_limiter=None):
    score = score_with_judge(judge_client, query, answer, rate_limiter=rate_limiter)
    return write_signal(session, "judge_trend", score, meta={"query": query})


def judge_trend_average(session: Session, window: int = 20) -> float | None:
    rows = read_signal_window(session, "judge_trend", limit=window)
    if not rows:
        return None
    return sum(r.value for r in rows) / len(rows)
