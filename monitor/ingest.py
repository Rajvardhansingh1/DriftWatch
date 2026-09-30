"""Wires demo-bot traffic into the signal analyzers and the rolling
window store. Purely observational — never blocks or modifies a request."""
from __future__ import annotations

from sqlalchemy.orm import Session

from monitor.db.writer import write_signal
from monitor.signals.embedding_drift import embed_texts, embedding_drift_score
from monitor.signals.self_consistency import self_consistency_disagreement_from_texts


def record_embedding_drift(session: Session, baseline_texts: list[str], current_texts: list[str]):
    baseline_emb = embed_texts(baseline_texts)
    current_emb = embed_texts(current_texts)
    score = embedding_drift_score(baseline_emb, current_emb)
    return write_signal(
        session,
        "embedding_drift",
        score,
        meta={"baseline_n": len(baseline_texts), "current_n": len(current_texts)},
    )


def record_self_consistency(session: Session, query: str, samples: list[str]):
    score = self_consistency_disagreement_from_texts(samples)
    return write_signal(
        session, "self_consistency", score, meta={"query": query, "n_samples": len(samples)}
    )
