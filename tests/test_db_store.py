import tempfile
import threading
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from monitor.db.session import _make_sqlite_engine, get_session, init_db
from monitor.db.writer import read_signal_window, write_signal


def make_memory_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(engine=engine)
    return engine


def test_write_signal_persists_timestamp_and_value():
    engine = make_memory_engine()
    session = get_session(engine=engine)
    record = write_signal(session, "embedding_drift", 0.42, meta={"n": 10})
    assert record.id is not None
    assert record.timestamp is not None
    assert record.value == 0.42
    assert record.signal == "embedding_drift"


def test_read_signal_window_returns_most_recent_first():
    engine = make_memory_engine()
    session = get_session(engine=engine)
    for v in [0.1, 0.2, 0.3]:
        write_signal(session, "self_consistency", v)
    rows = read_signal_window(session, "self_consistency", limit=2)
    assert len(rows) == 2
    assert rows[0].value == 0.3
    assert rows[1].value == 0.2


def test_read_signal_window_filters_by_signal_name():
    engine = make_memory_engine()
    session = get_session(engine=engine)
    write_signal(session, "embedding_drift", 0.5)
    write_signal(session, "self_consistency", 0.9)
    rows = read_signal_window(session, "embedding_drift", limit=10)
    assert len(rows) == 1
    assert rows[0].signal == "embedding_drift"


def test_concurrent_writes_to_a_real_sqlite_file_do_not_raise():
    # Regression: FastAPI runs sync route handlers in a thread pool, so
    # request threads and the canary scheduler thread can write at the
    # same time. Without WAL mode + a busy timeout, sqlite3 raises
    # "database is locked" under this contention (see decision.md D-011).
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "concurrent.sqlite3"
        engine = _make_sqlite_engine(f"sqlite:///{db_path}")
        init_db(engine=engine)

        errors: list[Exception] = []

        def writer(n: int):
            try:
                session = get_session(engine=engine)
                for i in range(10):
                    write_signal(session, "embedding_drift", float(i))
                session.close()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        session = get_session(engine=engine)
        rows = read_signal_window(session, "embedding_drift", limit=100)
        assert len(rows) == 80
        session.close()
        engine.dispose()  # release file handles before TemporaryDirectory cleans up (Windows)
