"""The agent uses a low-memory form of the same MMD; it must agree with the server's reference version."""
import numpy as np
import pytest

from driftwatch_llm.core.embedding import embedding_drift_score, embedding_drift_score_fast, rbf_mmd2, rbf_mmd2_fast


@pytest.mark.parametrize("dim", [2, 8, 384])
@pytest.mark.parametrize("shift", [0.0, 0.5, 3.0])
def test_fast_mmd_matches_the_reference(dim, shift):
    rng = np.random.default_rng(dim * 7 + int(shift * 10))
    x = rng.normal(size=(40, dim))
    y = rng.normal(loc=shift, size=(25, dim))
    assert rbf_mmd2_fast(x, y) == pytest.approx(rbf_mmd2(x, y), rel=1e-6, abs=1e-9)
    assert embedding_drift_score_fast(x, y) == pytest.approx(embedding_drift_score(x, y), rel=1e-6, abs=1e-9)


def test_fast_mmd_is_non_negative_and_zero_for_identical_samples():
    x = np.random.default_rng(0).normal(size=(30, 16))
    assert rbf_mmd2_fast(x, x) == pytest.approx(0.0, abs=1e-12)
    assert embedding_drift_score_fast(x, x) >= 0.0


def test_fast_mmd_works_on_float32_unit_vectors_and_never_builds_a_3d_array():
    rng = np.random.default_rng(1)
    x = rng.normal(size=(200, 384)).astype(np.float32)
    y = rng.normal(loc=0.2, size=(20, 384)).astype(np.float32)
    x /= np.linalg.norm(x, axis=1, keepdims=True)
    y /= np.linalg.norm(y, axis=1, keepdims=True)
    import tracemalloc

    tracemalloc.start()
    value = rbf_mmd2_fast(x, y)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert value >= 0.0
    assert peak < 20 * 1024 * 1024, f"peak {peak / 1e6:.0f} MB (the reference version needs about 150 MB here)"
