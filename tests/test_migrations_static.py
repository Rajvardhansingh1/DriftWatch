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


def test_0006_definer_functions_pin_empty_search_path():
    sql = _sql("0006_api_keys_ingest.sql")
    fns = re.findall(r"create function [\w.]+\(.*?\n\$\$;", sql, flags=re.S)
    assert len(fns) >= 3
    for fn in fns:
        if "security definer" in fn:
            assert "set search_path = ''" in fn, fn[:80]


def test_0006_api_key_hash_is_never_client_selectable():
    sql = _sql("0006_api_keys_ingest.sql")
    grant = re.search(r"grant select \(([^)]*)\)\s+on public\.project_api_keys", sql)
    assert grant and "key_hash" not in grant.group(1)


def test_0006_ingest_event_is_the_only_anon_executable_function():
    sql = _sql("0006_api_keys_ingest.sql")
    assert re.findall(r"grant execute on function (public\.\w+)\([^)]*\) to anon", sql) == ["public.ingest_event"]


def test_0007_has_retention_realtime_and_ping():
    sql = _sql("0007_retention_realtime_ping.sql")
    assert "create extension if not exists pg_cron" in sql
    assert "cron.schedule(" in sql and "if exists (select 1 from pg_extension" not in sql
    assert "create table public.signal_hourly" in sql
    assert "revoke all on public.signal_hourly from anon" in sql
    assert "alter publication supabase_realtime add table public.signal_records" in sql
    assert "create function public.ping()" in sql


def test_keepalive_workflow_pings_supabase_daily():
    root = MIGRATIONS[0].parent.parent.parent
    text = (root / ".github" / "workflows" / "supabase-keepalive.yml").read_text(encoding="utf-8")
    assert "cron:" in text and "/rest/v1/rpc/ping" in text
    assert "secrets.SUPABASE_ANON_KEY" in text


def test_0007_indexes_occurred_at_for_nightly_prune():
    sql = _sql("0007_retention_realtime_ping.sql")
    idx = "create index signal_records_occurred_at_idx on public.signal_records (occurred_at);"
    assert idx in sql
    assert sql.index(idx) < sql.index("create function private.rollup_and_prune()")


def test_0008_functions_are_safe_and_not_anon():
    sql = _sql("0008_console_functions.sql")
    fns = re.findall(r"create function [\w.]+\(.*?\n\$\$;", sql, flags=re.S)
    assert len(fns) == 3
    for fn in fns:
        assert "set search_path = ''" in fn, fn[:60]
    assert not re.search(r"to [^;]*\banon\b", sql)
    for name in ("create_project(text)", "delete_my_account()", "export_my_data()"):
        assert f"revoke all on function public.{name} from public, anon" in sql
        assert f"grant execute on function public.{name} to authenticated" in sql


def test_0008_delete_account_order_and_export_hides_key_hash():
    sql = _sql("0008_console_functions.sql")
    body = sql.split("create function public.delete_my_account")[1]
    assert body.index("write_audit") < body.index("delete from public.organizations") < body.index("delete from auth.users")
    assert "delete from public.project_api_keys where created_by" in body
    export = sql.split("create function public.export_my_data")[1]
    assert "key_hash" not in export
    assert "limit 10000" in export
    assert "signal_records_latest_10000" in export and "20000" not in export


def test_0008_create_project_serialises_per_user():
    sql = _sql("0008_console_functions.sql")
    body = sql.split("create function public.create_project")[1].split("create function public.delete_my_account")[0]
    assert "pg_advisory_xact_lock(hashtextextended(v_uid::text, 0))" in body
    assert body.index("pg_advisory_xact_lock") < body.index("from public.organization_members")


def test_0008_export_signal_records_is_index_friendly():
    sql = _sql("0008_console_functions.sql")
    export = sql.split("create function public.export_my_data")[1]
    assert "project_id in (select id from public.projects)" in export
    assert "order by occurred_at desc limit 10000" in export


def test_0008_security_modes():
    sql = _sql("0008_console_functions.sql")
    export = sql.split("create function public.export_my_data")[1]
    assert "security invoker" in export and "security definer" not in export
    for name in ("create_project", "delete_my_account"):
        body = sql.split(f"create function public.{name}")[1].split("$$;")[0]
        assert "security definer" in body


def test_0008_closes_direct_project_insert_and_rollback_restores():
    sql = _sql("0008_console_functions.sql")
    assert 'drop policy "projects_insert_admin" on public.projects;' in sql
    assert "revoke insert on public.projects from authenticated;" in sql
    down = (MIGRATIONS[0].parent.parent / "rollback" / "0008_down.sql").read_text(encoding="utf-8")
    assert "grant insert on public.projects to authenticated;" in down
    assert 'create policy "projects_insert_admin" on public.projects for insert' in down
    assert down.index("create policy") < down.index("drop function")


def test_0008_limit_counts_all_created_orgs_and_project_updates_restricted():
    sql = _sql("0008_console_functions.sql")
    body = sql.split("create function public.create_project")[1].split("create function public.delete_my_account")[0]
    assert "o.created_by = v_uid" in body
    assert body.index("o.created_by = v_uid") < body.index("insert into public.organizations")
    assert "revoke update on public.projects from authenticated;" in sql
    assert "grant update (name, settings) on public.projects to authenticated;" in sql
    down = (MIGRATIONS[0].parent.parent / "rollback" / "0008_down.sql").read_text(encoding="utf-8")
    assert down.index("revoke update (name, settings) on public.projects from authenticated;") < down.index(
        "grant update on public.projects to authenticated;")


def test_0008_hard_denies_anon_on_projects():
    assert "revoke all on public.projects from anon;" in _sql("0008_console_functions.sql")


# ---- 0009: device-code login for the CLI -------------------------------------

ANON_0009 = {"public.start_device_login", "public.poll_device_login", "public.revoke_api_key_by_secret"}
AUTHED_0009 = {"public.inspect_device_login", "public.approve_device_login", "public.deny_device_login"}


def _fn_body(sql: str, header: str) -> str:
    m = re.search(rf"create function {re.escape(header)}.*?\n\$\$;", sql, re.S)
    assert m, header
    return m.group(0)


def test_0009_device_tables_are_private_with_rls():
    sql = _sql("0009_device_auth.sql")
    for t in ("device_codes", "device_attempts", "device_start_rate"):
        assert f"create table private.{t}" in sql
        assert f"alter table private.{t} enable row level security" in sql
    assert "create table public." not in sql


def test_0009_device_code_is_stored_hashed_only():
    sql = _sql("0009_device_auth.sql")
    assert "device_code_hash bytea not null unique" in sql
    assert not re.search(r"\bdevice_code\s+text\b", sql)


def test_0009_anon_grants_are_exactly_the_three_device_functions():
    sql = _sql("0009_device_auth.sql")
    anon = set(re.findall(r"grant execute on function ([\w.]+)\([^)]*\) to [^;]*\banon\b", sql))
    assert anon == ANON_0009


def test_0009_approval_functions_are_authenticated_only():
    sql = _sql("0009_device_auth.sql")
    for fn in AUTHED_0009:
        assert re.search(rf"revoke all on function {re.escape(fn)}\([^)]*\) from public, anon;", sql), fn
        assert re.search(rf"grant execute on function {re.escape(fn)}\([^)]*\) to authenticated;", sql), fn


def test_0009_definer_functions_pin_empty_search_path():
    sql = _sql("0009_device_auth.sql")
    fns = re.findall(r"create function [\w.]+\(.*?\n\$\$;", sql, flags=re.S)
    assert len(fns) >= 9
    for fn in fns:
        assert "set search_path = ''" in fn, fn[:70]


def test_0009_wrong_codes_are_counted_without_raising():
    body = _fn_body(_sql("0009_device_auth.sql"), "private.find_device_code")
    at = body.index("insert into private.device_attempts")
    tail = body[at:body.index("return", at)]
    assert "raise exception" not in tail  # a raise would roll the counter back


def test_0009_user_code_alphabet_and_rejection_sampling():
    sql = _sql("0009_device_auth.sql")
    assert "'BCDFGHJKLMNPQRSTVWXZ'" in sql
    assert "< 240" in sql  # 240 = 12 * 20: every letter equally likely


def test_0009_poll_rechecks_approver_role_and_consumes_once():
    body = _fn_body(_sql("0009_device_auth.sql"), "public.poll_device_login")
    assert "m.role in ('owner', 'admin')" in body
    assert body.count("consumed_at = now()") >= 3
    for status in ("expired_token", "slow_down", "authorization_pending", "access_denied", "key_limit"):
        assert f"'{status}'" in body


def test_0009_audit_results_fit_the_check_constraint():
    sql = _sql("0009_device_auth.sql")
    calls = re.findall(r"write_audit\((.*?)\);", sql, re.S)
    assert calls
    for call in calls:
        assert re.search(r"'(ok|denied|error)'\s*$", call.strip()), call


def test_0009_prune_job_and_rollback():
    sql = _sql("0009_device_auth.sql")
    assert "cron.schedule('driftwatch-device-prune'" in sql
    down = (MIGRATIONS[0].parent.parent / "rollback" / "0009_down.sql").read_text(encoding="utf-8")
    assert "cron.unschedule('driftwatch-device-prune')" in down
    for fn in ANON_0009 | AUTHED_0009:
        assert f"drop function if exists {fn}(" in down
    for t in ("device_codes", "device_attempts", "device_start_rate"):
        assert f"drop table if exists private.{t}" in down
