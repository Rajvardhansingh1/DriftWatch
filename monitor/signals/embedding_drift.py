"""Embedding-space drift: rolling window of live outputs vs a stable
baseline, compared with Maximum Mean Discrepancy (RBF kernel).
The math and the embedder factory live in driftwatch_llm.core.embedding; this module keeps the
server's lazy embedder (chosen by settings) and re-exports the rest."""
from __future__ import annotations

import numpy as np

from driftwatch_llm.core.embedding import (  # noqa: F401
    OnnxEmbedder as _OnnxEmbedder,
    _median_heuristic_gamma,
    embedding_drift_score,
    make_embedder,
    rbf_mmd2,
)

_embedder = None


def get_embedder():
    global _embedder
    if _embedder is None:
        from monitor.config import settings

        _embedder = make_embedder(settings.embedder)
    return _embedder


def embed_texts(texts: list[str]) -> np.ndarray:
    return np.asarray(get_embedder().encode(list(texts)))
