from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from demo_bot.bot import QABot
from monitor.db.session import get_session, init_db
from monitor.db.writer import read_signal_window
from monitor.signals.canary_probes import CanaryCache, Probe
from monitor.signals.scheduler import CANARY_JOB_ID, run_canary_job, start_canary_scheduler


class FakeLLMClient:
    def complete(self, system_prompt, query, model, temperature=0.0):
        return "Paris"


def make_session_factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    init_db(engine=engine)
    return engine, lambda: get_session(engine=engine)


def test_run_canary_job_writes_canary_accuracy_signal():
    engine, session_factory = make_session_factory()
    bot = QABot(client=FakeLLMClient())
    probes = [Probe(id="p1", prompt="capital of France?", expected_answer="Paris")]
    run_canary_job(bot, probes, session_factory, CanaryCache())
    rows = read_signal_window(session_factory(), "canary_accuracy")
    assert len(rows) == 1
    assert rows[0].value == 1.0


def test_start_canary_scheduler_registers_job_at_configured_interval():
    engine, session_factory = make_session_factory()
    bot = QABot(client=FakeLLMClient())
    probes = [Probe(id="p1", prompt="capital of France?", expected_answer="Paris")]
    scheduler = start_canary_scheduler(bot, probes, session_factory, interval_minutes=15)
    try:
        job = scheduler.get_job(CANARY_JOB_ID)
        assert job is not None
        assert job.trigger.interval.total_seconds() == 15 * 60
    finally:
        scheduler.shutdown(wait=False)
