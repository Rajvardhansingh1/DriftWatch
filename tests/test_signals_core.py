import numpy as np

from monitor.signals.embedding_drift import embedding_drift_score, rbf_mmd2
from monitor.signals.self_consistency import (
    pairwise_cosine_agreement,
    self_consistency_disagreement,
)


def test_mmd_is_zero_for_identical_distributions():
    rng = np.random.default_rng(0)
    x = rng.normal(size=(30, 8))
    assert rbf_mmd2(x, x) == 0.0


def test_mmd_is_positive_for_shifted_distribution():
    rng = np.random.default_rng(0)
    baseline = rng.normal(loc=0.0, size=(50, 8))
    shifted = rng.normal(loc=5.0, size=(50, 8))
    score = embedding_drift_score(baseline, shifted)
    assert score > 0.3


def test_mmd_is_near_zero_for_same_distribution_resampled():
    rng = np.random.default_rng(1)
    baseline = rng.normal(size=(50, 8))
    current = rng.normal(size=(50, 8))
    score = embedding_drift_score(baseline, current)
    assert score < 0.2


def test_embedding_drift_score_never_negative():
    rng = np.random.default_rng(2)
    a = rng.normal(size=(10, 4))
    b = rng.normal(size=(10, 4))
    assert embedding_drift_score(a, b) >= 0.0


def test_pairwise_cosine_agreement_is_one_for_identical_vectors():
    embeddings = np.tile(np.array([1.0, 0.0, 0.0]), (5, 1))
    assert pairwise_cosine_agreement(embeddings) == 1.0


def test_pairwise_cosine_agreement_is_zero_for_orthogonal_vectors():
    embeddings = np.array([[1.0, 0.0], [0.0, 1.0]])
    assert abs(pairwise_cosine_agreement(embeddings)) < 1e-9


def test_self_consistency_disagreement_high_for_orthogonal_answers():
    embeddings = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 0.0]])
    disagreement = self_consistency_disagreement(embeddings)
    assert disagreement > 0.3


def test_self_consistency_disagreement_low_for_consistent_answers():
    embeddings = np.tile(np.array([0.5, 0.5, 0.5]), (4, 1))
    disagreement = self_consistency_disagreement(embeddings)
    assert disagreement == 0.0


def test_self_consistency_single_sample_is_fully_consistent():
    embeddings = np.array([[1.0, 2.0, 3.0]])
    assert self_consistency_disagreement(embeddings) == 0.0
