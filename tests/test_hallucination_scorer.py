"""Mirrors P1-SentinelaiFraudCopilotProject/tests/test_hallucination_scorer.py
so the vendored copy is verified against the same behavior contract as the
original (D-005: reused, not reimplemented)."""
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from monitor.db.session import get_session, init_db
from monitor.db.writer import read_signal_window
from monitor.signals.hallucination_scorer import score_grounded, score_ungrounded
from monitor.signals.hallucination_signal import record_hallucination_score


def test_grounded_fully_supported():
    context = "Vendor is Acme Corp. Total is 42.50. Purchased on 2026-01-01."
    response = "The vendor is Acme Corp. The total is 42.50."
    result = score_grounded(response, context)
    assert result.mode == "grounded"
    assert result.score == 0.0


def test_grounded_fully_unsupported():
    context = "Vendor is Acme Corp. Total is 42.50."
    response = "The spaceship launched to Mars yesterday."
    result = score_grounded(response, context)
    assert result.score == 1.0


def test_grounded_partial_support():
    context = "Vendor is Acme Corp. Total is 42.50."
    response = "The vendor is Acme Corp. The spaceship launched to Mars."
    result = score_grounded(response, context)
    assert 0.0 < result.score < 1.0


def test_grounded_empty_response():
    result = score_grounded("", "some context")
    assert result.score == 0.0


def test_ungrounded_identical_samples_low_score():
    samples = ["the total is 42.50", "the total is 42.50"]
    result = score_ungrounded(samples)
    assert result.mode == "ungrounded"
    assert result.score == 0.0


def test_ungrounded_divergent_samples_high_score():
    samples = ["the total is 42.50", "aliens built the pyramids"]
    result = score_ungrounded(samples)
    assert result.score > 0.5


def test_ungrounded_single_sample_returns_zero():
    result = score_ungrounded(["only one sample"])
    assert result.score == 0.0


def make_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    init_db(engine=engine)
    return get_session(engine=engine)


def test_record_hallucination_score_uses_grounded_mode_when_context_given():
    session = make_session()
    record_hallucination_score(
        session, response_text="The vendor is Acme.", grounding_context="Vendor is Acme."
    )
    rows = read_signal_window(session, "hallucination_score")
    assert len(rows) == 1
    assert rows[0].value == 0.0


def test_record_hallucination_score_falls_back_to_self_consistency_without_context():
    session = make_session()
    record_hallucination_score(
        session,
        response_text="the total is 42.50",
        samples=["the total is 42.50", "aliens built the pyramids"],
    )
    rows = read_signal_window(session, "hallucination_score")
    assert len(rows) == 1
    assert rows[0].value > 0.5
