"""Local check of the migrations and SQL tests, no Supabase project needed.

Starts an embedded Postgres, builds a minimal Supabase shim (roles, auth.uid(),
extensions.digest/gen_random_bytes, a stub cron schema, the realtime publication),
applies supabase/migrations/*.sql and runs supabase/tests/*.sql, rolling each back.

    pip install pgserver psycopg2-binary      # in a throwaway venv, not the project env
    python scripts/run_sql_tests_local.py [UPTO_MIGRATION_NUMBER] [TEST_PREFIX ...]

This is a shim, not Supabase: it catches SQL and logic mistakes, not platform quirks.
The real project (apply_migration + the SQL editor) stays the authority.
"""
import re
import sys
import tempfile
from pathlib import Path

import pgserver
import psycopg2

REPO = Path(__file__).resolve().parent.parent
UPTO = int(sys.argv[1]) if len(sys.argv) > 1 else 99
ONLY_TESTS = sys.argv[2:]  # e.g. 0004

SHIM = """
create role anon nologin;
create role authenticated nologin;
create role service_role nologin;
create schema auth;
create schema extensions;
create function extensions.digest(t text, alg text) returns bytea language sql immutable as
  $$ select case when alg = 'sha256' then sha256(convert_to(t, 'utf8')) else null end $$;
create function extensions.digest(b bytea, alg text) returns bytea language sql immutable as
  $$ select case when alg = 'sha256' then sha256(b) else null end $$;
create function extensions.gen_random_bytes(n int) returns bytea language plpgsql volatile as $$
declare out bytea := ''::bytea;
begin
  while length(out) < n loop
    out := out || decode(replace(gen_random_uuid()::text, '-', ''), 'hex');
  end loop;
  return substring(out from 1 for n);
end $$;
create table auth.users (
  id uuid primary key, email text, email_confirmed_at timestamptz,
  raw_user_meta_data jsonb default '{}'::jsonb, created_at timestamptz default now());
create function auth.uid() returns uuid language sql stable as
  $$ select nullif(nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub', '')::uuid $$;
create schema cron;
create table cron.job (jobid serial primary key, jobname text unique, schedule text, command text);
create function cron.schedule(n text, s text, c text) returns bigint language sql as
  $$ insert into cron.job (jobname, schedule, command) values (n, s, c) returning jobid::bigint $$;
create function cron.unschedule(n text) returns boolean language sql as
  $$ with d as (delete from cron.job where jobname = n returning 1) select exists (select 1 from d) $$;
create publication supabase_realtime;
grant usage on schema public, extensions, auth to anon, authenticated;
alter default privileges in schema public grant all on tables to anon, authenticated;
alter default privileges in schema public grant all on functions to anon, authenticated;
alter default privileges in schema public grant all on sequences to anon, authenticated;
grant execute on function auth.uid() to anon, authenticated;
grant execute on all functions in schema extensions to anon, authenticated;
"""

tmp = Path(tempfile.mkdtemp(prefix="pgshim_"))
srv = pgserver.get_server(tmp, cleanup_mode="stop")
conn = psycopg2.connect(srv.get_uri())
conn.autocommit = True
cur = conn.cursor()
cur.execute(SHIM)

migs = sorted((REPO / "supabase" / "migrations").glob("*.sql"))
for m in migs:
    n = int(m.name.split("_", 1)[0])
    if n > UPTO:
        continue
    sql = m.read_text(encoding="utf-8")
    sql = re.sub(r"(?im)^create extension if not exists pg_cron;\s*$", "-- (shim) pg_cron", sql)
    sql = re.sub(r"(?im)^create extension if not exists pgcrypto with schema extensions;\s*$", "-- (shim) pgcrypto", sql)
    try:
        cur.execute(sql)
        print(f"applied  {m.name}")
    except Exception as e:  # noqa: BLE001
        print(f"FAILED   {m.name}: {str(e).strip()[:400]}")
        sys.exit(1)

failed = 0
for t in sorted((REPO / "supabase" / "tests").glob("*.sql")):
    if ONLY_TESTS and not any(t.name.startswith(o) for o in ONLY_TESTS):
        continue
    sql = t.read_text(encoding="utf-8")
    sql = re.sub(r"\brollback;\s*$", "", sql.rstrip())
    sql = re.sub(r"(?im)^begin;\s*$", "", sql, count=1)
    try:
        cur.execute("begin;")
        cur.execute(sql)
        row = cur.fetchone()
        print(f"test     {t.name}: {row[0]}")
        if row[0] != "PASS":
            failed += 1
    except Exception as e:  # noqa: BLE001
        failed += 1
        print(f"test     {t.name}: ERROR {str(e).strip()[:500]}")
    finally:
        cur.execute("rollback;")
        cur.execute("reset role;")
sys.exit(1 if failed else 0)
