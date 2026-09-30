from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from monitor.db.session import get_session, init_db
from monitor.db.writer import read_signal_window, write_signal
from monitor.scoring.combined_score import (
    ScoringConfig,
    combine_signals,
    compute_combined_score,
    normalize_signal,
)

STABLE_VALUES = {
    "embedding_drift": 0.05,
    "self_consistency": 0.05,
    "canary_accuracy": 0.98,
    "judge_trend": 0.9,
    "hallucination_score": 0.05,
}

DEGRADED_VALUES = {
    "embedding_drift": 0.9,
    "self_consistency": 0.85,
    "canary_accuracy": 0.2,
    "judge_trend": 0.3,
    "hallucination_score": 0.8,
}


def make_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    init_db(engine=engine)
    return get_session(engine=engine)


def test_normalize_signal_inverts_higher_is_better_signals():
    assert normalize_signal("canary_accuracy", 1.0) == 0.0
    assert normalize_signal("canary_accuracy", 0.0) == 1.0
    assert normalize_signal("judge_trend", 1.0) == 0.0
    assert normalize_signal("embedding_drift", 0.7) == 0.7


def test_combine_signals_is_deterministic():
    r1 = combine_signals(STABLE_VALUES)
    r2 = combine_signals(STABLE_VALUES)
    assert r1.score == r2.score
    assert r1.contributions == r2.contributions


def test_combine_signals_stable_traffic_does_not_alert():
    result = combine_signals(STABLE_VALUES)
    assert result.alert is False
    assert result.score < 0.6


def test_combine_signals_degraded_traffic_alerts():
    result = combine_signals(DEGRADED_VALUES)
    assert result.alert is True
    assert result.score >= 0.6


def test_combine_signals_reports_triggering_signals():
    result = combine_signals(DEGRADED_VALUES)
    assert "embedding_drift" in result.triggering_signals
    assert "canary_accuracy" in result.triggering_signals
    assert "hallucination_score" in result.triggering_signals


def test_combine_signals_respects_custom_weights():
    config = ScoringConfig(
        weights={
            "embedding_drift": 1.0,
            "self_consistency": 0.0,
            "canary_accuracy": 0.0,
            "judge_trend": 0.0,
            "hallucination_score": 0.0,
        },
        alert_threshold=0.6,
    )
    values = {**STABLE_VALUES, "embedding_drift": 0.9}
    result = combine_signals(values, config=config)
    assert result.score == 0.9


def test_combine_signals_custom_alert_threshold():
    config = ScoringConfig(alert_threshold=0.99)
    result = combine_signals(DEGRADED_VALUES, config=config)
    assert result.alert is False


def test_compute_combined_score_reads_latest_from_store_and_persists():
    session = make_session()
    for name, value in STABLE_VALUES.items():
        write_signal(session, name, value)
    result = compute_combined_score(session)
    assert result.alert is False
    rows = read_signal_window(session, "combined_score")
    assert len(rows) == 1
    assert rows[0].value == result.score


def test_compute_combined_score_uses_most_recent_value_per_signal():
    session = make_session()
    for name, value in STABLE_VALUES.items():
        write_signal(session, name, value)
    for name, value in DEGRADED_VALUES.items():
        write_signal(session, name, value)
    result = compute_combined_score(session)
    assert result.alert is True


def test_compute_combined_score_missing_signals_treated_as_zero_weight():
    session = make_session()
    write_signal(session, "embedding_drift", 0.1)
    result = compute_combined_score(session)
    assert 0.0 <= result.score <= 1.0
