import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

import monitor.ingest as ingest
from monitor.db.session import get_session, init_db
from monitor.db.writer import read_signal_window


def make_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    init_db(engine=engine)
    return get_session(engine=engine)


def test_record_embedding_drift_writes_signal_row(monkeypatch):
    session = make_session()
    monkeypatch.setattr(
        ingest, "embed_texts", lambda texts: np.tile(np.array([1.0, 0.0]), (len(texts), 1))
    )
    ingest.record_embedding_drift(session, baseline_texts=["a", "b"], current_texts=["c", "d"])
    rows = read_signal_window(session, "embedding_drift")
    assert len(rows) == 1
    assert rows[0].value >= 0.0


def test_record_self_consistency_writes_signal_row(monkeypatch):
    session = make_session()
    monkeypatch.setattr(
        ingest,
        "self_consistency_disagreement_from_texts",
        lambda samples: 0.33,
    )
    ingest.record_self_consistency(session, query="what is 2+2?", samples=["4", "four"])
    rows = read_signal_window(session, "self_consistency")
    assert len(rows) == 1
    assert rows[0].value == 0.33
