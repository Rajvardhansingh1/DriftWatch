"""APScheduler wrapper that runs the fixed canary probe set on a timer
and writes the resulting accuracy into the rolling window store."""
from __future__ import annotations

from datetime import datetime
from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session

from demo_bot.bot import QABot
from monitor.db.writer import write_signal
from monitor.signals.canary_probes import CanaryCache, Probe, run_canary_batch

CANARY_JOB_ID = "canary_probe_job"

SessionFactory = Callable[[], Session]


def run_canary_job(
    bot: QABot, probes: list[Probe], session_factory: SessionFactory, cache: CanaryCache
) -> dict:
    # A fresh session per run — the scheduler executes on its own thread
    # alongside concurrent API requests, so it must not share a Session
    # (SQLAlchemy Sessions aren't safe for cross-thread reuse).
    session = session_factory()
    try:
        result = run_canary_batch(bot, probes, cache=cache)
        write_signal(session, "canary_accuracy", result["accuracy"], meta={"n_probes": len(probes)})
        return result
    finally:
        session.close()


def start_canary_scheduler(
    bot: QABot,
    probes: list[Probe],
    session_factory: SessionFactory,
    interval_minutes: int,
    cache: CanaryCache | None = None,
) -> BackgroundScheduler:
    cache = cache or CanaryCache()
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_canary_job,
        "interval",
        minutes=interval_minutes,
        args=[bot, probes, session_factory, cache],
        id=CANARY_JOB_ID,
        # Fire once immediately so canary_accuracy has data right away
        # instead of waiting a full interval — the demo needs the signal
        # to react "within seconds" of a scenario click, not minutes.
        next_run_time=datetime.now(),
    )
    scheduler.start()
    return scheduler
