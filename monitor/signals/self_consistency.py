"""Self-consistency: re-run the same live query at temperature > 0 and
measure pairwise answer disagreement via embedding cosine similarity."""
from __future__ import annotations

import numpy as np

from monitor.signals.embedding_drift import embed_texts


def pairwise_cosine_agreement(embeddings: np.ndarray) -> float:
    n = embeddings.shape[0]
    if n < 2:
        return 1.0
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    unit = embeddings / norms
    sims = unit @ unit.T
    i, j = np.triu_indices(n, k=1)
    return float(sims[i, j].mean())


def self_consistency_disagreement(embeddings: np.ndarray) -> float:
    return max(0.0, float(1.0 - pairwise_cosine_agreement(embeddings)))


def self_consistency_disagreement_from_texts(samples: list[str]) -> float:
    return self_consistency_disagreement(embed_texts(samples))
