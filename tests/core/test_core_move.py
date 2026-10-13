"""The pure detector code lives in driftwatch_llm.core; monitor/ re-exports it unchanged."""
import subprocess
import sys

import monitor.cloud.ingest as m_ingest
import monitor.scoring.combined_score as m_score
import monitor.signals.embedding_drift as m_embed
import monitor.signals.hallucination_scorer as m_hall
import monitor.signals.self_consistency as m_cons
import monitor.sync.outbox as m_outbox
from driftwatch_llm.core import backoff, consistency, embedding, events, hallucination, scoring


def test_monitor_modules_expose_the_same_objects_as_core():
    assert m_embed.rbf_mmd2 is embedding.rbf_mmd2
    assert m_embed.embedding_drift_score is embedding.embedding_drift_score
    assert m_embed._median_heuristic_gamma is embedding._median_heuristic_gamma
    assert m_cons.pairwise_cosine_agreement is consistency.pairwise_cosine_agreement
    assert m_cons.self_consistency_disagreement is consistency.self_consistency_disagreement
    assert m_hall.score_grounded is hallucination.score_grounded
    assert m_hall.score_ungrounded is hallucination.score_ungrounded
    assert m_hall.HallucinationResult is hallucination.HallucinationResult
    assert m_score._DEFAULT_WEIGHTS is scoring._DEFAULT_WEIGHTS
    assert m_score.normalize_signal is scoring.normalize_signal
    assert m_score.ALL_SIGNALS is scoring.ALL_SIGNALS
    assert m_score.CombinedScoreResult is scoring.CombinedScoreResult
    assert m_ingest.validate_event is events.validate_event
    assert m_ingest.IngestionError is events.IngestionError
    assert m_ingest.InMemoryIdempotencyStore is events.InMemoryIdempotencyStore
    assert m_outbox.backoff_seconds is backoff.backoff_seconds
    assert m_outbox.MAX_ATTEMPTS is backoff.MAX_ATTEMPTS


def test_monitor_combine_signals_gives_the_same_answers_as_core():
    values = {"embedding_drift": 0.3, "self_consistency": 0.1, "judge_trend": 0.9}
    a = m_score.combine_signals(values)
    b = scoring.combine_signals(values)
    assert (a.score, a.contributions, a.triggering_signals, a.alert) == (
        b.score, b.contributions, b.triggering_signals, b.alert)


def test_core_default_threshold_is_the_tuned_value_and_monitor_follows_settings(monkeypatch):
    assert scoring.ScoringConfig().alert_threshold == 0.17
    monkeypatch.setattr(m_score.settings, "alert_threshold", 0.42)
    assert m_score.ScoringConfig().alert_threshold == 0.42
    # monitor's combine_signals uses the settings-driven default, as before the move
    assert m_score.combine_signals({"embedding_drift": 0.3}).alert is False
    monkeypatch.setattr(m_score.settings, "alert_threshold", 0.2)
    assert m_score.combine_signals({"embedding_drift": 0.3}).alert is True


def test_numpy_free_core_modules_import_without_numpy():
    code = (
        "import sys; sys.modules['numpy'] = None\n"
        "import driftwatch_llm.core.events, driftwatch_llm.core.scoring, "
        "driftwatch_llm.core.hallucination, driftwatch_llm.core.backoff\n"
        "print('ok')\n"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip() == "ok", r.stderr


def test_core_does_not_import_the_server_package():
    code = (
        "import sys\n"
        "import driftwatch_llm.core.events, driftwatch_llm.core.scoring, driftwatch_llm.core.backoff, "
        "driftwatch_llm.core.hallucination\n"
        "assert not any(m == 'monitor' or m.startswith('monitor.') for m in sys.modules), "
        "[m for m in sys.modules if m.startswith('monitor')]\n"
        "assert 'sqlalchemy' not in sys.modules\n"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_the_server_imports_without_the_cli_and_agent_dependencies():
    """Render installs requirements-lean.txt only: no typer, keyring, platformdirs, portalocker or httpx2."""
    code = (
        "import sys\n"
        "for name in ('typer', 'keyring', 'platformdirs', 'portalocker', 'fastembed'):\n"
        "    sys.modules[name] = None\n"
        "import monitor.main\n"
        "import monitor.cloud.ingest, monitor.scoring.combined_score, monitor.signals.embedding_drift\n"
        "assert 'driftwatch_llm.cli' not in sys.modules and 'driftwatch_llm.agent' not in sys.modules\n"
        "print('ok')\n"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env={**__import__("os").environ, "DRIFTWATCH_FORCE_SIMULATED": "true"})
    assert r.returncode == 0 and r.stdout.strip().endswith("ok"), r.stderr[-800:]


def test_make_embedder_passes_local_files_only_only_when_asked(monkeypatch):
    import sys
    import types

    seen = []

    class FakeTE:
        def __init__(self, name, **kwargs):
            seen.append(kwargs)

        def embed(self, texts):
            return iter([])

    monkeypatch.setitem(sys.modules, "fastembed", types.SimpleNamespace(TextEmbedding=FakeTE))
    embedding.make_embedder("onnx")
    embedding.make_embedder("onnx", local_only=True)
    assert seen == [{}, {"local_files_only": True}]  # the server's behaviour is unchanged


def test_hash_embedder_is_deterministic_normalised_and_separates_topics():
    import numpy as np

    emb = embedding.make_embedder("hash")
    a1, a2, b = emb.encode(["Your invoice renews monthly on the plan", "Your invoice renews monthly on the plan", "Roast the carrots with salt in the oven"])
    assert a1.shape == (256,) and np.allclose(a1, a2) and abs(np.linalg.norm(a1) - 1.0) < 1e-5
    same = emb.encode(["The invoice for your plan renews monthly"])[0]
    assert float(a1 @ same) > float(a1 @ b) + 0.2  # same topic is closer than a different one
    assert np.all(np.isfinite(emb.encode([""])))  # an empty text still gives a valid vector
