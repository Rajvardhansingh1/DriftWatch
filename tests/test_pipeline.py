from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from demo_bot.bot import QABot
from demo_bot.simulated_client import SimulatedLLMClient
from monitor.db.session import get_session, init_db
from monitor.pipeline import PipelineState, run_query_cycle


def make_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    init_db(engine=engine)
    return get_session(engine=engine)


def make_state():
    client = SimulatedLLMClient()
    bot = QABot(client=client)
    return PipelineState(bot=bot, judge_client=client, baseline_texts=["Paris is the capital of France."])


def test_run_query_cycle_returns_score_and_response():
    state = make_state()
    session = make_session()
    result = run_query_cycle(state, session, query_text="What is the capital of France?")
    assert "Paris" in result["response"]
    assert 0.0 <= result["score"] <= 1.0
    assert result["llm_calls"] == 4  # 1 primary + 3 self-consistency samples


def test_run_query_cycle_counts_judge_call_every_fourth_cycle():
    state = make_state()
    session = make_session()
    calls = [run_query_cycle(state, session, query_text="q")["llm_calls"] for _ in range(4)]
    assert calls[:3] == [4, 4, 4]
    assert calls[3] == 5  # 4th cycle also samples the judge


def test_run_query_cycle_uses_auto_loop_query_when_no_text_given():
    state = make_state()
    session = make_session()
    result = run_query_cycle(state, session, query_text=None)
    assert result["query"] is not None


def test_run_query_cycle_skips_embedding_drift_with_empty_baseline_texts():
    # Regression: an empty baseline_texts (e.g. startup seeding failed,
    # D-025) must not feed embedding_drift/combined_score NaN - a silent
    # failure mode worse than a crash, since NaN >= threshold is always
    # False and alerting would just quietly stop working.
    client = SimulatedLLMClient()
    bot = QABot(client=client)
    state = PipelineState(bot=bot, judge_client=client, baseline_texts=[])
    session = make_session()
    for _ in range(6):
        result = run_query_cycle(state, session, query_text="What is the capital of France?")
    assert result["score"] == result["score"]  # not NaN
    assert 0.0 <= result["score"] <= 1.0
