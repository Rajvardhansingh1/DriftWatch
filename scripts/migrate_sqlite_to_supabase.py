"""SQLite -> Supabase historical data migration (Spec_Upgrade.md Phase 3,
Mandatory Supplement C). Migrates `signal_records` rows from a local
DriftWatch SQLite file into the cloud `signal_records` table.

Dry-run (default) makes NO writes to Supabase and does not even require
a target connection - it only reads the source file and reports what
would happen. Real execution requires --execute, a --database-url
(Postgres connection string, never hardcoded), and an explicit
--organization-id/--project-id (Mandatory Supplement C.2: legacy rows
must never be silently assigned a tenant).

Usage:
    python scripts/migrate_sqlite_to_supabase.py --source ./data/driftwatch.sqlite3
    python scripts/migrate_sqlite_to_supabase.py --source ./data/driftwatch.sqlite3 \\
        --execute --database-url postgresql://... \\
        --organization-id <uuid> --project-id <uuid>
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class MigrationReport:
    source_path: str
    source_exists: bool
    candidate_count: int = 0
    imported_count: int = 0
    skipped_count: int = 0
    quarantined_count: int = 0
    failed_count: int = 0
    quarantine_reasons: list[str] = field(default_factory=list)
    dry_run: bool = True

    def summary(self) -> str:
        lines = [
            f"source: {self.source_path} (exists={self.source_exists})",
            f"mode: {'DRY RUN (no writes)' if self.dry_run else 'EXECUTE'}",
            f"candidates: {self.candidate_count}",
            f"imported: {self.imported_count}",
            f"skipped: {self.skipped_count}",
            f"quarantined: {self.quarantined_count}",
            f"failed: {self.failed_count}",
        ]
        if self.quarantine_reasons:
            lines.append("quarantine reasons:")
            lines.extend(f"  - {r}" for r in self.quarantine_reasons)
        return "\n".join(lines)


def _rows_from_source(source_path: Path):
    """Reads every signal_records row from the source SQLite file,
    read-only. Never mutates the source file (Mandatory Supplement C.3:
    'Keep source databases intact')."""
    uri = f"file:{source_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            "select id, timestamp, signal, value, meta from signal_records order by id"
        )
        yield from cursor
    finally:
        conn.close()


def _validate_row(row: sqlite3.Row) -> tuple[dict | None, str | None]:
    """Type-converts and validates one source row per the mapping matrix
    (Docs/Phase_Upgrade_Guide.md section 5.1). Returns (converted, None)
    on success or (None, reason) if the row must be quarantined rather
    than silently dropped."""
    try:
        occurred_at = datetime.fromisoformat(row["timestamp"])
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError) as exc:
        return None, f"row {row['id']}: unparseable timestamp {row['timestamp']!r}: {exc}"

    meta_raw = row["meta"]
    meta: dict = {}
    if meta_raw:
        try:
            meta = json.loads(meta_raw)
            if not isinstance(meta, dict):
                return None, f"row {row['id']}: meta did not decode to a JSON object"
        except json.JSONDecodeError as exc:
            return None, f"row {row['id']}: meta failed JSON validation: {exc}"

    return {
        "legacy_signal_id": row["id"],
        "occurred_at": occurred_at.isoformat(),
        "signal": row["signal"],
        "value": row["value"],
        "meta": meta,
    }, None


def dry_run(source: Path) -> MigrationReport:
    report = MigrationReport(source_path=str(source), source_exists=source.exists())
    if not report.source_exists:
        # Not an error: this is the expected, correct outcome when no
        # real SQLite file has ever been populated (confirmed true for
        # this checkout - see Phase_Upgrade_Guide.md section 1.4/2.3).
        return report

    for row in _rows_from_source(source):
        report.candidate_count += 1
        converted, reason = _validate_row(row)
        if reason:
            report.quarantined_count += 1
            report.quarantine_reasons.append(reason)
        else:
            report.skipped_count += 1  # dry-run: valid, but not written
    return report


def execute(
    source: Path,
    database_url: str,
    organization_id: str,
    project_id: str,
    batch_size: int = 500,
) -> MigrationReport:
    uuid.UUID(organization_id)  # raises ValueError if not a valid uuid - fail loud, not silent
    uuid.UUID(project_id)

    # Lazy import: psycopg2 is only needed for real execution, not for
    # dry-run or the rest of the application - no new hard dependency
    # for everyone who never runs a real migration.
    import psycopg2
    import psycopg2.extras

    report = MigrationReport(source_path=str(source), source_exists=source.exists(), dry_run=False)
    if not report.source_exists:
        return report

    conn = psycopg2.connect(database_url)
    try:
        conn.autocommit = False
        batch: list[dict] = []
        with conn.cursor() as cur:
            for row in _rows_from_source(source):
                report.candidate_count += 1
                converted, reason = _validate_row(row)
                if reason:
                    report.quarantined_count += 1
                    report.quarantine_reasons.append(reason)
                    continue
                batch.append(converted)
                if len(batch) >= batch_size:
                    _write_batch(cur, batch, organization_id, project_id, report)
                    batch = []
            if batch:
                _write_batch(cur, batch, organization_id, project_id, report)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return report


def _write_batch(cur, batch: list[dict], organization_id: str, project_id: str, report: MigrationReport) -> None:
    import psycopg2.extras

    # Idempotent upsert keyed on (project_id, legacy_signal_id): a
    # re-run after a partial failure never double-inserts the same
    # source row (Mandatory Supplement C.3).
    psycopg2.extras.execute_values(
        cur,
        """
        insert into signal_records (project_id, signal, value, meta, occurred_at, legacy_signal_id)
        values %s
        on conflict (project_id, legacy_signal_id) do nothing
        """,
        [
            (
                project_id,
                row["signal"],
                row["value"],
                json.dumps(row["meta"]),
                row["occurred_at"],
                row["legacy_signal_id"],
            )
            for row in batch
        ],
    )
    report.imported_count += len(batch)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="./data/driftwatch.sqlite3")
    parser.add_argument("--execute", action="store_true", help="Actually write to Supabase")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--organization-id", default=None)
    parser.add_argument("--project-id", default=None)
    args = parser.parse_args()

    source = Path(args.source)

    if not args.execute:
        report = dry_run(source)
        print(report.summary())
        return 0

    if not (args.database_url and args.organization_id and args.project_id):
        print(
            "ERROR: --execute requires --database-url, --organization-id, and --project-id "
            "(legacy rows are never assigned a tenant automatically).",
            file=sys.stderr,
        )
        return 2

    report = execute(source, args.database_url, args.organization_id, args.project_id)
    print(report.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
