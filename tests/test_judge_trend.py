import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from demo_bot.bot import STRONG_MODEL
from monitor.db.session import get_session, init_db
from monitor.signals.judge_trend import (
    judge_trend_average,
    record_judge_score,
    score_with_judge,
)


class FakeJudgeClient:
    def __init__(self, reply: str):
        self.reply = reply

    def complete(self, system_prompt, query, model, temperature=0.0):
        return self.reply


def make_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    init_db(engine=engine)
    return get_session(engine=engine)


def test_score_with_judge_defaults_to_a_real_model_id():
    # Regression: the default was the placeholder string "judge", which
    # SimulatedLLMClient tolerated (it detects judge prompts by content,
    # not model name) but a real provider (Groq) rejects with a 404
    # model_not_found - only ever caught when running against the real
    # API, since every test uses a fake/simulated client (D-023).
    class RecordingJudgeClient:
        def complete(self, system_prompt, query, model, temperature=0.0):
            self.seen_model = model
            return "8"

    judge = RecordingJudgeClient()
    score_with_judge(judge, "q", "a")
    assert judge.seen_model == STRONG_MODEL
    assert judge.seen_model != "judge"


def test_score_with_judge_parses_number_and_normalizes():
    judge = FakeJudgeClient("8")
    score = score_with_judge(judge, "q", "a")
    assert score == 0.8


def test_score_with_judge_parses_number_from_surrounding_text():
    judge = FakeJudgeClient("I'd say this is about a 7.5 out of 10.")
    score = score_with_judge(judge, "q", "a")
    assert score == 0.75


def test_score_with_judge_clamps_out_of_range_scores():
    judge = FakeJudgeClient("15")
    score = score_with_judge(judge, "q", "a")
    assert score == 1.0


def test_score_with_judge_raises_on_unparseable_output():
    judge = FakeJudgeClient("I refuse to answer.")
    with pytest.raises(ValueError):
        score_with_judge(judge, "q", "a")


def test_record_judge_score_writes_signal_row():
    session = make_session()
    judge = FakeJudgeClient("9")
    record_judge_score(session, judge, "q", "a")
    avg = judge_trend_average(session)
    assert avg == 0.9


def test_judge_trend_average_tracks_trend_not_single_score():
    session = make_session()
    for reply in ["10", "0", "10", "0"]:
        record_judge_score(session, FakeJudgeClient(reply), "q", "a")
    avg = judge_trend_average(session)
    assert avg == 0.5


def test_judge_trend_average_returns_none_with_no_data():
    session = make_session()
    assert judge_trend_average(session) is None
