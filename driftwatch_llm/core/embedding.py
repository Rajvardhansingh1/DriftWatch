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


def make_embedder(kind: str):
    """"onnx" builds the fastembed (ONNX) embedder; anything else builds sentence-transformers (torch)."""
    if kind == "onnx":
        from fastembed import TextEmbedding

        return OnnxEmbedder(TextEmbedding(f"sentence-transformers/{MODEL_NAME}"))
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL_NAME)


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
