"""Adapts the vendored hallucination scorer into the fifth DriftWatch
signal: claim-level entailment when grounding context is available,
self-consistency sampling as the fallback otherwise (spec §5)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from monitor.db.writer import write_signal
from monitor.signals.hallucination_scorer import score_grounded, score_ungrounded


def record_hallucination_score(
    session: Session,
    response_text: str,
    grounding_context: str | None = None,
    samples: list[str] | None = None,
):
    if grounding_context:
        result = score_grounded(response_text, grounding_context)
    else:
        result = score_ungrounded(samples or [response_text])
    return write_signal(session, "hallucination_score", result.score, meta={"mode": result.mode})
