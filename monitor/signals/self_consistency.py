"""Self-consistency: re-run the same live query at temperature > 0 and
measure pairwise answer disagreement via embedding cosine similarity.
The math lives in driftwatch_llm.core.consistency; this module adds the text entry point."""
from __future__ import annotations

from driftwatch_llm.core.consistency import (  # noqa: F401
    pairwise_cosine_agreement,
    self_consistency_disagreement,
)
from monitor.signals.embedding_drift import embed_texts


def self_consistency_disagreement_from_texts(samples: list[str]) -> float:
    return self_consistency_disagreement(embed_texts(samples))
