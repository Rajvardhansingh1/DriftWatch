"""Launch gate J3: every public table and every public function is exercised by a SQL test, so nothing ships untested.

The SQL tests (supabase/tests/*.sql) run in CI on a scratch Postgres (the `sql` job). This static check fails when a
migration adds a table or function that no SQL test mentions at all.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS = sorted((ROOT / "supabase" / "migrations").glob("*.sql"))
SQL_TESTS = sorted((ROOT / "supabase" / "tests").glob("*.sql"))


def _text(paths):
    return "\n".join(p.read_text(encoding="utf-8") for p in paths)


def test_every_public_table_appears_in_a_sql_test():
    migrations = _text(MIGRATIONS)
    tests = _text(SQL_TESTS)
    tables = set(re.findall(r"create table public\.(\w+)", migrations))
    missing = sorted(t for t in tables if t not in tests)
    assert not missing, f"public tables with no SQL test: {missing} (add them to a file in supabase/tests/)"


def test_every_public_function_appears_in_a_sql_test():
    migrations = _text(MIGRATIONS)
    tests = _text(SQL_TESTS)
    created = set(re.findall(r"create (?:or replace )?function public\.(\w+)", migrations))
    dropped = set(re.findall(r"drop function (?:if exists )?public\.(\w+)", migrations))
    missing = sorted(f for f in created - dropped if f not in tests)
    assert not missing, f"public functions with no SQL test: {missing} (add them to a file in supabase/tests/)"


def test_every_migration_has_a_rollback_note():
    rollbacks = {p.name.split("_")[0] for p in (ROOT / "supabase" / "rollback").glob("*_down.sql")}
    # 0001-0004 predate the rollback folder
    missing = [p.name for p in MIGRATIONS if int(p.name.split("_")[0]) >= 5 and p.name.split("_")[0] not in rollbacks]
    assert not missing, f"migrations without a rollback file: {missing}"


def test_the_sql_ci_job_runs_every_sql_test_script():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    for script in ("run_sql_tests_local.py", "test_quota_concurrency_local.py", "test_runner_concurrency_local.py",
                   "test_runner_e2e_local.py", "test_runbook_local.py", "test_switches_local.py"):
        assert script in ci, f"the CI sql job does not run {script}"
        assert (ROOT / "scripts" / script).is_file()
