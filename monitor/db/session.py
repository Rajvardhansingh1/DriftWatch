from __future__ import annotations

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from monitor.config import settings
from monitor.db.models import Base

_engine: Engine | None = None
_SessionFactory: sessionmaker | None = None


def _make_sqlite_engine(url: str) -> Engine:
    # FastAPI runs sync route handlers in a thread pool, so the scheduler
    # thread and concurrent request threads can genuinely hit this engine
    # at the same time. A plain sqlite3 connection raises "database is
    # locked" immediately on write contention; `timeout` makes it wait
    # instead, and WAL mode lets readers and a writer proceed together.
    engine = create_engine(
        url, connect_args={"check_same_thread": False, "timeout": 30}
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    return engine


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = _make_sqlite_engine(f"sqlite:///{settings.db_path}")
    return _engine


def init_db(engine: Engine | None = None) -> None:
    Base.metadata.create_all(engine or get_engine())


def get_session(engine: Engine | None = None) -> Session:
    if engine is not None:
        return sessionmaker(bind=engine)()
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=get_engine())
    return _SessionFactory()
