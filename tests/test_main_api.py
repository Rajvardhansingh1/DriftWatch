from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

from demo_bot.simulated_client import SimulatedLLMClient
from monitor.db.session import get_session, init_db
from monitor.main import create_app
from monitor.signals.canary_probes import Probe


def make_test_app():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    init_db(engine=engine)
    session_factory = lambda: get_session(engine=engine)
    probes = [Probe(id="p1", prompt="What is the capital of France?", expected_answer="Paris")]
    return create_app(
        llm_client=SimulatedLLMClient(),
        session_factory=session_factory,
        probes=probes,
    )


def test_health_endpoint():
    app = make_test_app()
    with TestClient(app) as client:
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "embedding_drift_active": True}


def test_health_reports_embedding_drift_inactive_when_seeding_fails():
    # Regression: a startup seeding failure (D-025) must be visible via
    # the API, not only server logs - a broken provider key would
    # otherwise look identical to "server just started".
    import monitor.main as main_module

    original = main_module.seed_baseline_texts
    main_module.seed_baseline_texts = lambda client: (_ for _ in ()).throw(
        RuntimeError("simulated provider outage")
    )
    try:
        app = make_test_app()
        with TestClient(app) as client:
            resp = client.get("/api/health")
            assert resp.json() == {"status": "ok", "embedding_drift_active": False}
    finally:
        main_module.seed_baseline_texts = original


def test_quota_endpoint_starts_at_zero_used():
    app = make_test_app()
    with TestClient(app) as client:
        resp = client.get("/api/quota")
        body = resp.json()
        assert body["used"] == 0
        assert body["exceeded"] is False


def test_query_endpoint_returns_score_and_response():
    app = make_test_app()
    with TestClient(app) as client:
        resp = client.post("/api/query", json={"text": "What is the capital of France?"})
        assert resp.status_code == 200
        body = resp.json()
        assert "Paris" in body["response"]
        assert 0.0 <= body["score"] <= 1.0
        assert isinstance(body["triggering_signals"], list)
        assert body["cached"] is False


def test_scenario_state_reflects_multiple_independently_active_scenarios():
    # Regression: scenarios are independent flags on the bot, not
    # mutually exclusive - activating a second one without resetting
    # the first stacks both (D-026). A UI that only remembers "the last
    # button clicked" would hide that the first one is still active.
    app = make_test_app()
    with TestClient(app) as client:
        state = client.get("/api/scenario/state").json()
        assert state == {
            "model_downgraded": False,
            "injection_active": False,
            "distribution_shift_active": False,
        }

        client.post("/api/scenario/model-downgrade", json={"action": "activate"})
        client.post("/api/scenario/injection-creep", json={"action": "activate"})

        state = client.get("/api/scenario/state").json()
        assert state["model_downgraded"] is True
        assert state["injection_active"] is True
        assert state["distribution_shift_active"] is False


def test_query_endpoint_increments_quota():
    app = make_test_app()
    with TestClient(app) as client:
        client.post("/api/query", json={"text": "hello"})
        quota = client.get("/api/quota").json()
        assert quota["used"] > 0


def test_signals_endpoint_returns_all_five_signals_and_combined_score():
    app = make_test_app()
    with TestClient(app) as client:
        client.post("/api/query", json={"text": "What is the capital of France?"})
        resp = client.get("/api/signals")
        body = resp.json()
        for name in [
            "embedding_drift",
            "self_consistency",
            "canary_accuracy",
            "judge_trend",
            "hallucination_score",
            "combined_score",
        ]:
            assert name in body


def test_score_endpoint_reflects_latest_combined_score():
    app = make_test_app()
    with TestClient(app) as client:
        client.post("/api/query", json={"text": "What is the capital of France?"})
        resp = client.get("/api/score")
        body = resp.json()
        assert "score" in body
        assert "alert" in body
        assert "triggering_signals" in body


def test_model_downgrade_scenario_activates_and_resets_via_api():
    app = make_test_app()
    with TestClient(app) as client:
        resp = client.post("/api/scenario/model-downgrade", json={"action": "activate"})
        assert resp.json()["model_id"].endswith("gpt-oss-20b")
        resp = client.post("/api/scenario/model-downgrade", json={"action": "reset"})
        assert resp.json()["model_id"].endswith("gpt-oss-120b")


def test_unknown_scenario_returns_404():
    app = make_test_app()
    with TestClient(app) as client:
        resp = client.post("/api/scenario/not-a-real-scenario", json={"action": "activate"})
        assert resp.status_code == 404


def test_invalid_scenario_action_returns_400():
    app = make_test_app()
    with TestClient(app) as client:
        resp = client.post("/api/scenario/model-downgrade", json={"action": "sideways"})
        assert resp.status_code == 400


def test_scenario_activation_survives_internal_rate_limit_exhaustion():
    # Regression: /api/scenario/{name}'s immediate canary re-run shares
    # SharedRateLimiter with /api/query. Previously an exhausted budget
    # crashed the endpoint as a 500 instead of still applying the
    # scenario state change.
    app = make_test_app()
    app.state.shared_rate_limiter.max_calls = 0
    with TestClient(app) as client:
        resp = client.post("/api/scenario/model-downgrade", json={"action": "activate"})
        assert resp.status_code == 200
        assert resp.json()["model_id"].endswith("gpt-oss-20b")


def test_reset_all_scenarios_endpoint():
    app = make_test_app()
    with TestClient(app) as client:
        client.post("/api/scenario/model-downgrade", json={"action": "activate"})
        client.post("/api/scenario/distribution-shift", json={"action": "activate"})
        resp = client.post("/api/scenario/reset")
        assert resp.status_code == 200


def test_quota_exhaustion_returns_cached_snapshot_without_new_llm_calls():
    app = make_test_app()
    app.state.quota.limit = 1
    with TestClient(app) as client:
        client.post("/api/query", json={"text": "What is the capital of France?"})
        resp = client.post("/api/query", json={"text": "What is the capital of Japan?"})
        body = resp.json()
        assert body["cached"] is True
        assert body["response"] is None


def test_query_text_over_max_length_is_rejected():
    app = make_test_app()
    with TestClient(app) as client:
        resp = client.post("/api/query", json={"text": "x" * 501})
        assert resp.status_code == 422


def test_signals_limit_is_capped_and_floored():
    app = make_test_app()
    with TestClient(app) as client:
        client.post("/api/query", json={"text": "What is the capital of France?"})
        resp_huge = client.get("/api/signals?limit=999999999")
        assert resp_huge.status_code == 200
        resp_negative = client.get("/api/signals?limit=-5")
        assert resp_negative.status_code == 200


def test_server_starts_even_when_baseline_seeding_fails():
    # Regression: a provider outage during startup seeding must not
    # crash the whole server (D-025) - this is exactly what happened
    # with a real Groq 429 at startup before the fix.
    class DeadOnArrivalClient(SimulatedLLMClient):
        def complete(self, *args, **kwargs):
            raise RuntimeError("simulated provider outage at startup")

    app = make_test_app()
    import monitor.main as main_module

    original = main_module.seed_baseline_texts
    main_module.seed_baseline_texts = lambda client: (_ for _ in ()).throw(
        RuntimeError("simulated provider outage")
    )
    try:
        with TestClient(app) as client:
            resp = client.get("/api/health")
            assert resp.status_code == 200
    finally:
        main_module.seed_baseline_texts = original


def test_provider_style_failure_degrades_to_cached_snapshot_not_500():
    # Regression: a real provider's own failure (groq.RateLimitError,
    # APIConnectionError, ...) is a different exception class per SDK,
    # not our own RateLimitExceeded - only caught once /api/query
    # started catching Exception broadly instead of one specific type
    # (D-024). This simulates "the provider itself blew up".
    class FlakyClient(SimulatedLLMClient):
        def complete(self, *args, **kwargs):
            raise RuntimeError("simulated provider outage")

    app = make_test_app()
    app.state.pipeline.bot.client = FlakyClient()
    with TestClient(app) as client:
        resp = client.post("/api/query", json={"text": "What is the capital of France?"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["cached"] is True
        assert body["response"] is None


def test_internal_rate_limit_exhaustion_degrades_to_cached_snapshot_not_500():
    # Regression: one /api/query fans out into up to 5 LLM calls sharing
    # SharedRateLimiter with the judge. Under load that budget trips
    # before the HTTP-level slowapi limit, and previously raised an
    # unhandled RateLimitExceeded -> 500 instead of degrading gracefully.
    app = make_test_app()
    app.state.shared_rate_limiter.max_calls = 2
    with TestClient(app) as client:
        resp = client.post("/api/query", json={"text": "What is the capital of France?"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["cached"] is True
        assert body["response"] is None
