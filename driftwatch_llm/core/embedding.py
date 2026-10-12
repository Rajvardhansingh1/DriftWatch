"""Embedding-space drift math (Maximum Mean Discrepancy, RBF kernel) and the embedder factory.

numpy is required here; fastembed / sentence-transformers are imported only when an embedder is built.
"""
from __future__ import annotations

import numpy as np

MODEL_NAME = "all-MiniLM-L6-v2"


class OnnxEmbedder:
    """Gives fastembed the `.encode(list) -> array` shape SentenceTransformer has."""

    def __init__(self, model):
        self._model = model

    def encode(self, texts):
        return np.stack(list(self._model.embed(texts)))


def make_embedder(kind: str, local_only: bool = False):
    """"onnx" builds the fastembed (ONNX) embedder; anything else builds sentence-transformers (torch).

    local_only=True never touches the network: it raises if the model is not already cached."""
    if kind == "onnx":
        from fastembed import TextEmbedding

        extra = {"local_files_only": True} if local_only else {}
        return OnnxEmbedder(TextEmbedding(f"sentence-transformers/{MODEL_NAME}", **extra))
    from sentence_transformers import SentenceTransformer

    extra = {"local_files_only": True} if local_only else {}
    return SentenceTransformer(MODEL_NAME, **extra)


def _median_heuristic_gamma(x: np.ndarray, y: np.ndarray) -> float:
    """Standard RBF-kernel bandwidth choice (Gretton et al.): gamma set
    from the median pairwise squared distance in the pooled sample, so
    the kernel is calibrated to the embedding space's actual scale
    instead of a fixed 1/n_features that's far too small for real
    (e.g. 384-dim) sentence embeddings and makes the kernel nearly
    insensitive to genuine semantic distance."""
    pooled = np.vstack([x, y])
    diffs = pooled[:, None, :] - pooled[None, :, :]
    sq_dists = (diffs**2).sum(-1)
    i, j = np.triu_indices(len(pooled), k=1)
    median_sq_dist = float(np.median(sq_dists[i, j])) if len(i) else 0.0
    return 1.0 / median_sq_dist if median_sq_dist > 0 else 1.0


def rbf_mmd2(x: np.ndarray, y: np.ndarray, gamma: float | None = None) -> float:
    """Squared MMD between samples x and y under an RBF kernel. 0 for
    identical distributions, grows with distributional distance."""
    if gamma is None:
        gamma = _median_heuristic_gamma(x, y)

    def kernel(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        sq_dists = ((a[:, None, :] - b[None, :, :]) ** 2).sum(-1)
        return np.exp(-gamma * sq_dists)

    kxx = kernel(x, x).mean()
    kyy = kernel(y, y).mean()
    kxy = kernel(x, y).mean()
    return float(kxx + kyy - 2 * kxy)


def embedding_drift_score(baseline_embeddings: np.ndarray, current_embeddings: np.ndarray) -> float:
    return max(0.0, rbf_mmd2(baseline_embeddings, current_embeddings))


# ---- low-memory form used by the local agent ------------------------------------------------------
# Same quantity as rbf_mmd2 above. The reference version builds an (n, n, d) difference array (about
# 150 MB for a 200-sample baseline of 384-d vectors); this one uses |a-b|^2 = |a|^2 + |b|^2 - 2ab,
# so only (n, n) matrices exist. tests/core/test_embedding_fast.py pins the two to 1e-6.


def _sq_dists(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    d = (a * a).sum(axis=1)[:, None] + (b * b).sum(axis=1)[None, :] - 2.0 * (a @ b.T)
    return np.maximum(d, 0.0)


def _median_heuristic_gamma_fast(x: np.ndarray, y: np.ndarray) -> float:
    pooled = np.vstack([np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)])
    sq = _sq_dists(pooled, pooled)
    i, j = np.triu_indices(len(pooled), k=1)
    median_sq_dist = float(np.median(sq[i, j])) if len(i) else 0.0
    return 1.0 / median_sq_dist if median_sq_dist > 0 else 1.0


def rbf_mmd2_fast(x: np.ndarray, y: np.ndarray, gamma: float | None = None) -> float:
    if gamma is None:
        gamma = _median_heuristic_gamma_fast(x, y)
    kxx = np.exp(-gamma * _sq_dists(x, x)).mean()
    kyy = np.exp(-gamma * _sq_dists(y, y)).mean()
    kxy = np.exp(-gamma * _sq_dists(x, y)).mean()
    return float(kxx + kyy - 2 * kxy)


def embedding_drift_score_fast(baseline_embeddings: np.ndarray, current_embeddings: np.ndarray) -> float:
    return max(0.0, rbf_mmd2_fast(baseline_embeddings, current_embeddings))
