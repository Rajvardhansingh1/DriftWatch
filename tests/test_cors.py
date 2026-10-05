from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

from demo_bot.simulated_client import SimulatedLLMClient
from monitor.config import settings
from monitor.db.session import get_session, init_db
from monitor.main import create_app


def make_app(monkeypatch, origins):
    monkeypatch.setattr(settings, "cors_origins", origins)
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


def test_allowed_origin_gets_cors_header(monkeypatch):
    client = TestClient(make_app(monkeypatch, "https://driftwatch.vercel.app"))
    resp = client.get("/api/health", headers={"Origin": "https://driftwatch.vercel.app"})
    assert resp.headers.get("access-control-allow-origin") == "https://driftwatch.vercel.app"


def test_unlisted_origin_gets_no_cors_header(monkeypatch):
    client = TestClient(make_app(monkeypatch, "https://driftwatch.vercel.app"))
    resp = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in resp.headers
