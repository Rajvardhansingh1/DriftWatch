"""Self-consistency math: pairwise cosine agreement between embeddings."""
from __future__ import annotations

import numpy as np


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
