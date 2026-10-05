"""FastAPI monitor service. Purely observational: it serves the demo bot,
runs the five signal analyzers on its traffic, and exposes the rolling
store + combined score to the dashboard. It never blocks or modifies a
request on behalf of anything else."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded as SlowApiRateLimitExceeded
from slowapi.util import get_remote_address

from demo_bot import scenarios
from demo_bot.bot import STRONG_MODEL, QABot
from demo_bot.llm_client import get_default_client
from demo_bot.simulated_client import SimulatedLLMClient
from sqlalchemy import text

from monitor import logging_redaction
from monitor.admin.routes import router as admin_router
from monitor.cloud.ingest_route import build_router as build_ingest_router
from monitor.cloud.supabase_store import SupabaseSignalStore
from monitor.config import settings
from monitor.db.session import get_session, init_db
from monitor.db.writer import read_signal_window
from monitor.pipeline import PipelineState, run_query_cycle
from monitor.quota import QuotaTracker
from monitor.rate_limit import SharedRateLimiter
from monitor.scoring.combined_score import ALL_SIGNALS, compute_combined_score
from monitor.signals.canary_probes import CanaryCache, load_probes
from monitor.signals.scheduler import run_canary_job, start_canary_scheduler

logger = logging.getLogger("driftwatch")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CANARY_PROBES_PATH = DATA_DIR / "canary_probes.yaml"

BASELINE_QUERIES = [
    "What is the capital of France?",
    "What is the capital of Japan?",
    "What is 12 + 7?",
    "At sea level, what temperature in Celsius does water boil at?",
    "What is the largest planet in our solar system?",
]


class ScenarioAction(BaseModel):
    action: str  # "activate" | "reset"


class QueryRequest(BaseModel):
    # Free-text goes through embedding + an LLM call; an unbounded string
    # is a cost/DoS vector (large embed, large provider payload/cost).
    text: str | None = Field(default=None, max_length=500)


def get_llm_client():
    if settings.force_simulated:
        return SimulatedLLMClient()
    try:
        return get_default_client()
    except RuntimeError:
        return SimulatedLLMClient()


def seed_baseline_texts(client) -> list[str]:
    """Run the fixed baseline query set through a clean, undegraded bot so
    embedding drift has a stable reference distribution to compare against.
    Dispatched concurrently (QABot.ask is a blocking sync call per query) so
    5 real provider round-trips at startup cost ~1 call's latency, not 5."""
    seed_bot = QABot(client=client)
    with ThreadPoolExecutor(max_workers=len(BASELINE_QUERIES)) as pool:
        return list(pool.map(lambda q: seed_bot.ask(q, temperature=0.0).text, BASELINE_QUERIES))


def create_app(
    *,
    llm_client=None,
    judge_client=None,
    session_factory=None,
    probes=None,
    seed_baseline: bool = True,
) -> FastAPI:
    logging_redaction.install()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Seeding makes real LLM calls when a real provider key is
        # configured - deferred here (ASGI startup) rather than done
        # eagerly in create_app(), so merely importing this module (as
        # every test does) never burns real API quota. Only an actual
        # server start (uvicorn, or TestClient's `with` block) seeds.
        if seed_baseline:
            try:
                app.state.pipeline.baseline_texts = seed_baseline_texts(client)
            except Exception:
                # A provider outage/rate-limit here must not take down the
                # whole server at startup. embedding_drift simply stays
                # inactive (pipeline.py guards on empty baseline_texts)
                # until a later successful call - see D-024/D-025.
                logger.warning(
                    "baseline seeding failed at startup, embedding_drift stays "
                    "inactive until the next restart",
                    exc_info=True,
                )
        app.state.canary_scheduler = start_canary_scheduler(
            app.state.bot,
            app.state.probes,
            app.state.session_factory,
            settings.canary_interval_minutes,
            cache=app.state.canary_cache,
        )
        yield
        if app.state.canary_scheduler is not None:
            app.state.canary_scheduler.shutdown(wait=False)

    app = FastAPI(title="DriftWatch Monitor", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

    limiter = Limiter(key_func=get_remote_address)
    app.state.limiter = limiter
    app.add_exception_handler(SlowApiRateLimitExceeded, _rate_limit_exceeded_handler)

    client = llm_client or get_llm_client()
    judge = judge_client or client

    if session_factory is None:
        init_db()
        session_factory = get_session

    app.state.session_factory = session_factory
    app.state.bot = QABot(client=client)
    app.state.judge_client = judge
    app.state.probes = probes if probes is not None else load_probes(str(CANARY_PROBES_PATH))
    app.state.canary_cache = CanaryCache()
    # Groq's free tier caps at 30 requests/minute; one /api/query fans out
    # to up to 5 calls, so 25 leaves headroom to stay under the real
    # provider ceiling instead of only reacting after Groq rejects one.
    app.state.shared_rate_limiter = SharedRateLimiter(max_calls=25, period_seconds=60)
    app.state.bot.rate_limiter = app.state.shared_rate_limiter
    app.state.quota = QuotaTracker(limit=settings.daily_quota)
    app.state.canary_scheduler = None

    app.state.pipeline = PipelineState(
        bot=app.state.bot,
        judge_client=judge,
        baseline_texts=[],
        rate_limiter=app.state.shared_rate_limiter,
    )

    @app.get("/api/health")
    def health():
        # embedding_drift_active surfaces a startup seeding failure
        # (D-025) here instead of only in server logs - a broken/expired
        # provider key would otherwise look identical to "just started".
        return {"status": "ok", "embedding_drift_active": bool(app.state.pipeline.baseline_texts)}

    @app.get("/api/ready")
    def ready():
        # Readiness (spec 13.2): the DB must answer. Liveness stays /api/health.
        session = None
        try:
            session = app.state.session_factory()
            session.execute(text("select 1"))
            return {"status": "ready"}
        except Exception:
            logger.exception("readiness check failed")
            raise HTTPException(status_code=503, detail="database unavailable")
        finally:
            if session is not None:
                session.close()

    app.include_router(admin_router)
    if settings.supabase_url and settings.supabase_anon_key:
        app.include_router(
            build_ingest_router(SupabaseSignalStore(settings.supabase_url, settings.supabase_anon_key))
        )

    @app.get("/api/quota")
    def quota():
        q: QuotaTracker = app.state.quota
        return {"used": q.used, "limit": q.limit, "remaining": q.remaining, "exceeded": q.exceeded}

    def _scenario_state_dict(bot: QABot) -> dict:
        # Ground truth for which degradations are actually active. The
        # three scenarios are independent flags on the bot (D-026) - a
        # UI that only remembers "the last button clicked" misrepresents
        # this the moment a visitor activates a second scenario without
        # resetting the first.
        return {
            "model_downgraded": bot.model_id != STRONG_MODEL,
            "injection_active": bot.prompt_version > 0,
            "distribution_shift_active": bot.distribution_shift_active,
        }

    @app.get("/api/scenario/state")
    def scenario_state():
        return _scenario_state_dict(app.state.bot)

    def _refresh_canary_if_budget_allows(bot: QABot) -> None:
        try:
            run_canary_job(bot, app.state.probes, app.state.session_factory, app.state.canary_cache)
        except Exception:
            # Scenario state change still applies; canary_accuracy just
            # keeps its last value. Covers our own SharedRateLimiter
            # (D-011/D-015) *and* the real provider failing - a real
            # provider's rate limit, timeout, or outage (groq.RateLimitError,
            # groq.APIConnectionError, ...) is a different exception class
            # per SDK and can't be exhaustively enumerated here; treat any
            # failure of an external call the same way (D-024).
            logger.exception("canary refresh failed, keeping last known value")

    @app.post("/api/scenario/reset")
    def reset_all_scenarios():
        scenarios.reset_all(app.state.bot)
        _refresh_canary_if_budget_allows(app.state.bot)
        return {"status": "reset"}

    @app.post("/api/scenario/{name}")
    def scenario(name: str, body: ScenarioAction):
        bot = app.state.bot
        handlers = {
            "model-downgrade": (scenarios.simulate_model_downgrade, scenarios.reset_model_downgrade),
            "injection-creep": (scenarios.simulate_injection_creep, scenarios.reset_injection_creep),
            "distribution-shift": (
                scenarios.simulate_distribution_shift,
                scenarios.reset_distribution_shift,
            ),
        }
        if name not in handlers:
            raise HTTPException(404, f"unknown scenario: {name}")
        activate, reset = handlers[name]
        if body.action == "activate":
            activate(bot)
        elif body.action == "reset":
            reset(bot)
        else:
            raise HTTPException(400, "action must be 'activate' or 'reset'")

        # Re-run canary immediately so canary_accuracy reacts to the
        # scenario within seconds instead of waiting for the next
        # scheduled interval (spec: dashboard reacts "within seconds").
        _refresh_canary_if_budget_allows(bot)

        return {
            "model_id": bot.model_id,
            "prompt_version": bot.prompt_version,
            "distribution_shift_active": bot.distribution_shift_active,
        }

    @app.post("/api/query")
    @limiter.limit(settings.rate_limit_per_session)
    def query(request: Request, body: QueryRequest):
        quota_tracker: QuotaTracker = app.state.quota
        if quota_tracker.exceeded:
            return _snapshot(app, cached=True)

        session = app.state.session_factory()
        try:
            cycle = run_query_cycle(app.state.pipeline, session, query_text=body.text or None)
            quota_tracker.increment(cycle["llm_calls"])
            return {
                "query": cycle["query"],
                "response": cycle["response"],
                "model_id": cycle["model_id"],
                "score": cycle["score"],
                "alert": cycle["alert"],
                "triggering_signals": cycle["triggering_signals"],
                "cached": False,
            }
        except Exception:
            # Covers our own SharedRateLimiter (D-011/D-015, tighter than
            # the HTTP-level slowapi limit since one /api/query fans out
            # into up to 5 LLM calls) *and* a real provider failing
            # (rate limit, timeout, outage - a different exception class
            # per SDK, not exhaustively enumerable here). Either way,
            # degrade to the cached snapshot instead of a 500 (D-024).
            logger.exception("query cycle failed, serving cached snapshot")
            return _snapshot(app, cached=True)
        finally:
            session.close()

    @app.get("/api/signals")
    def signals(limit: int = 50):
        limit = max(1, min(limit, 500))
        session = app.state.session_factory()
        try:
            out = {}
            for name in (*ALL_SIGNALS, "combined_score"):
                rows = read_signal_window(session, name, limit=limit)
                out[name] = [
                    {"timestamp": r.timestamp.isoformat(), "value": r.value} for r in reversed(rows)
                ]
            return out
        finally:
            session.close()

    @app.get("/api/score")
    def score():
        session = app.state.session_factory()
        try:
            result = compute_combined_score(session)
            return {
                "score": result.score,
                "alert": result.alert,
                "triggering_signals": result.triggering_signals,
                "contributions": result.contributions,
                "scenario": _scenario_state_dict(app.state.bot),
            }
        finally:
            session.close()

    return app


def _snapshot(app: FastAPI, cached: bool) -> dict:
    session = app.state.session_factory()
    try:
        result = compute_combined_score(session)
        return {
            "query": None,
            "response": None,
            "model_id": app.state.bot.model_id,
            "score": result.score,
            "alert": result.alert,
            "triggering_signals": result.triggering_signals,
            "cached": cached,
        }
    finally:
        session.close()


app = create_app()
