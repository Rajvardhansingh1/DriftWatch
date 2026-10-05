import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import migrate_sqlite_to_supabase as mig  # noqa: E402


def make_source(path: Path, rows: list[tuple]) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        "create table signal_records (id integer primary key autoincrement, "
        "timestamp datetime, signal varchar, value float, meta text)"
    )
    conn.executemany(
        "insert into signal_records (timestamp, signal, value, meta) values (?, ?, ?, ?)", rows
    )
    conn.commit()
    conn.close()


def test_dry_run_missing_source_is_a_clean_noop(tmp_path):
    report = mig.dry_run(tmp_path / "does-not-exist.sqlite3")
    assert report.source_exists is False
    assert report.candidate_count == 0
    assert report.imported_count == 0


def test_dry_run_counts_valid_rows_and_writes_nothing(tmp_path):
    src = tmp_path / "src.sqlite3"
    make_source(
        src,
        [
            ("2026-09-21T10:00:00", "embedding_drift", 0.1, json.dumps({"n": 3})),
            ("2026-09-21T10:01:00", "combined_score", 0.2, None),
        ],
    )
    before = src.read_bytes()
    report = mig.dry_run(src)
    assert report.candidate_count == 2
    assert report.skipped_count == 2  # dry-run: valid but not written
    assert report.imported_count == 0
    assert report.dry_run is True
    assert src.read_bytes() == before  # source never mutated


def test_bad_meta_json_is_quarantined_not_dropped(tmp_path):
    src = tmp_path / "src.sqlite3"
    make_source(src, [("2026-09-21T10:00:00", "embedding_drift", 0.1, "{not json")])
    report = mig.dry_run(src)
    assert report.quarantined_count == 1
    assert "meta failed JSON validation" in report.quarantine_reasons[0]


def test_unparseable_timestamp_is_quarantined(tmp_path):
    src = tmp_path / "src.sqlite3"
    make_source(src, [("not-a-date", "embedding_drift", 0.1, None)])
    report = mig.dry_run(src)
    assert report.quarantined_count == 1
    assert "unparseable timestamp" in report.quarantine_reasons[0]


def test_naive_timestamp_is_normalized_to_utc(tmp_path):
    src = tmp_path / "src.sqlite3"
    make_source(src, [("2026-09-21T10:00:00", "embedding_drift", 0.1, None)])
    with sqlite3.connect(src) as conn:
        row = conn.execute("select id, timestamp, signal, value, meta from signal_records").fetchone()
    converted, reason = mig._validate_row(
        {"id": row[0], "timestamp": row[1], "signal": row[2], "value": row[3], "meta": row[4]}
    )
    assert reason is None
    assert converted["occurred_at"].endswith("+00:00")


def test_execute_refuses_non_uuid_tenant(tmp_path):
    src = tmp_path / "src.sqlite3"
    make_source(src, [])
    with pytest.raises(ValueError):
        mig.execute(src, "postgresql://unused", "not-a-uuid", "00000000-0000-0000-0000-000000000000")
