"""Static checks on supabase/migrations/*.sql, run in CI via pytest.
These do not touch any database. They catch ordering mistakes, a table
created without RLS, and credential material accidentally committed."""
import re
from pathlib import Path

import pytest

MIGRATIONS = sorted((Path(__file__).resolve().parent.parent / "supabase" / "migrations").glob("*.sql"))


def test_migrations_exist_and_are_ordered():
    assert MIGRATIONS, "no migrations found"
    prefixes = [int(p.name.split("_", 1)[0]) for p in MIGRATIONS]
    assert prefixes == sorted(prefixes)
    assert len(set(prefixes)) == len(prefixes), "duplicate migration numbers"


@pytest.mark.parametrize("path", MIGRATIONS, ids=lambda p: p.name)
def test_every_created_public_table_enables_rls(path):
    sql = path.read_text(encoding="utf-8")
    created = set(re.findall(r"create table public\.(\w+)", sql))
    for table in created:
        assert re.search(rf"alter table public\.{table} enable row level security", sql), (
            f"{path.name}: table {table} created without RLS in the same migration"
        )


@pytest.mark.parametrize("path", MIGRATIONS, ids=lambda p: p.name)
def test_no_credential_material_in_migrations(path):
    sql = path.read_text(encoding="utf-8").lower()
    assert "service_role" not in sql
    assert not re.search(r"eyj[a-z0-9_\-]{10,}", sql), "JWT-shaped literal in migration"
    assert not re.search(r"gsk_[a-z0-9]{10,}", sql), "provider-key-shaped literal in migration"


def _sql(name: str) -> str:
    return (MIGRATIONS[0].parent / name).read_text(encoding="utf-8")


def test_0005_revokes_anon_on_known_definer_functions():
    sql = _sql("0005_security_hardening.sql")
    assert "revoke execute on function public.create_organization(text) from public, anon" in sql
    assert "public.rls_auto_enable()" in sql


def test_0005_policies_use_initplan_auth_uid():
    sql = _sql("0005_security_hardening.sql")
    policy_bodies = re.findall(r"create policy .*?;", sql, flags=re.S)
    assert policy_bodies
    for body in policy_bodies:
        bare = body.replace("(select auth.uid())", "")
        assert "auth.uid()" not in bare, body


def test_0005_locks_down_signal_records():
    sql = _sql("0005_security_hardening.sql")
    assert "revoke all on public.signal_records from anon" in sql
    assert "revoke insert on public.signal_records from authenticated" in sql
    assert "grant insert (project_id, event_id, signal, value, meta, occurred_at)" in sql
    assert "create trigger signal_records_guard" in sql
    assert "audit_events_select_org_admin" in sql
