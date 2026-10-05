from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

from demo_bot.simulated_client import SimulatedLLMClient
from monitor.db.session import get_session, init_db
from monitor.main import create_app


def make_app():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    init_db(engine=engine)
    return create_app(
        llm_client=SimulatedLLMClient(),
        session_factory=lambda: get_session(engine=engine),
        probes=[],
        seed_baseline=False,
    )


def test_ready_reports_ready_when_db_answers():
    with TestClient(make_app()) as client:
        resp = client.get("/api/ready")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ready"}


def test_ready_returns_503_when_db_broken():
    app = make_app()

    def broken_factory():
        raise RuntimeError("db gone")

    app.state.session_factory = broken_factory
    with TestClient(app) as client:
        resp = client.get("/api/ready")
        assert resp.status_code == 503
        assert "db gone" not in resp.text  # no internal detail leaked
