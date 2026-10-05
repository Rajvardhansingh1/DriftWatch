from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from monitor.db.repository import LocalSQLiteRepository
from monitor.db.session import get_session, init_db


def make_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    init_db(engine=engine)
    return get_session(engine=engine)


def test_local_sqlite_repository_round_trips_a_signal():
    repo = LocalSQLiteRepository(make_session())
    repo.write_signal("embedding_drift", 0.42, meta={"n": 3})
    rows = repo.read_signal_window("embedding_drift")
    assert len(rows) == 1
    assert rows[0].value == 0.42


def test_local_sqlite_repository_write_signal_stamps_schema_version():
    repo = LocalSQLiteRepository(make_session())
    repo.write_signal("self_consistency", 0.1)
    row = repo.read_signal_window("self_consistency")[0]
    import json

    assert json.loads(row.meta)["schema_version"] == 1
