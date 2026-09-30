import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from run_detection_eval import (  # noqa: E402
    run_canary_baseline,
    run_false_positive_eval,
    run_scenario_eval,
)


def test_model_downgrade_is_detected_with_a_measured_latency():
    result = run_scenario_eval("model-downgrade")
    assert result.detected is True
    assert isinstance(result.detection_latency_queries, int)
    assert result.detection_latency_queries >= 1
    assert len(result.triggering_signals_at_detection) > 0


def test_injection_creep_is_detected():
    result = run_scenario_eval("injection-creep")
    assert result.detected is True
    assert result.detection_latency_queries >= 1


def test_distribution_shift_is_detected():
    # Slower than the other two (embedding_drift needs the rolling
    # window to accumulate off-topic samples before MMD saturates -
    # this is a genuinely cumulative signal, not an instant spike).
    result = run_scenario_eval("distribution-shift")
    assert result.detected is True
    assert result.detection_latency_queries >= 1


def test_stable_traffic_produces_no_false_positives():
    result = run_false_positive_eval()
    assert result["queries_run"] > 0
    assert result["false_positive_rate"] == 0.0


def test_canary_baseline_is_measured_not_assumed():
    result = run_canary_baseline()
    assert result["n_probes"] > 0
    assert 0.0 <= result["accuracy"] <= 1.0
