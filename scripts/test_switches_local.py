"""Rehearses the kill switches on a scratch Postgres (needs the pgserver venv).

    python scripts/test_switches_local.py

For each switch: the guarded call works, then switches_off.sql makes it refuse (insufficient privilege), then
switches_on.sql restores it, and the full list of function grants after is IDENTICAL to the list before. Also rehearses
revoke_all_api_keys.sql. Exit code 1 on failure.
"""
import datetime
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
src = (REPO / "scripts" / "run_sql_tests_local.py").read_text(encoding="utf-8")
head = src[: src.index("failed = 0")]
head = head.replace("REPO = Path(__file__).resolve().parent.parent", f"REPO = Path(r'{REPO}')")
head = head.replace("UPTO = int(sys.argv[1]) if len(sys.argv) > 1 else 99", "UPTO = 99").replace("ONLY_TESTS = sys.argv[2:]", "ONLY_TESTS = []")
ns: dict = {}
exec(compile(head, "runner_head", "exec"), ns)
conn = ns["conn"]
conn.autocommit = True
cur = conn.cursor()
failures = []


def check(ok, name):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        failures.append(name)


def run_file(name):
    text = (REPO / "supabase" / "runbooks" / name).read_text(encoding="utf-8")
    sql = "\n".join(line for line in text.splitlines() if not line.strip().startswith("--"))  # comments may contain ';'
    cur.execute("reset role")
    for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
        cur.execute(stmt)


def grants():
    cur.execute(
        "select routine_name, grantee, privilege_type from information_schema.routine_privileges "
        "where routine_schema = 'public' order by 1, 2, 3"
    )
    return cur.fetchall()


def call(role, sql, params=(), jwt_sub=None):
    """Runs one statement as `role`; returns 'ok' or the SQLSTATE of the error."""
    cur.execute("reset role")
    cur.execute(f"set role {role}")
    if jwt_sub:
        cur.execute("select set_config('request.jwt.claims', %s, false)", ('{"sub":"%s","role":"%s"}' % (jwt_sub, role),))
    try:
        cur.execute(sql, params)
        return "ok"
    except Exception as exc:  # noqa: BLE001
        return getattr(exc, "pgcode", "error")
    finally:
        cur.execute("reset role")


# -- setup: a user with a project and a key, so every guarded call is meaningful
uid = str(uuid.uuid4())
cur.execute("insert into auth.users (id, email, email_confirmed_at) values (%s, 'u@t.local', now())", (uid,))
cur.execute("set role authenticated")
cur.execute("select set_config('request.jwt.claims', %s, false)", ('{"sub":"%s","role":"authenticated"}' % uid,))
cur.execute("select (public.create_project('P')).id")
pid = cur.fetchone()[0]
cur.execute("select public.create_project_api_key(%s, 'k')", (pid,))
key = cur.fetchone()[0]
cur.execute("reset role")
EVENT = '{"schema_version":1,"event_id":"%s","occurred_at":"%s","source":"t","signal":"embedding_drift","value":0.1,"meta":{}}'


def ingest():
    stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return call("anon", "select public.ingest_event(%s, %s::jsonb)", (key, EVENT % (uuid.uuid4(), stamp)))


def start_login():
    return call("anon", "select public.start_device_login('laptop', 'Linux')")


def new_key():
    return call("authenticated", "select public.create_project_api_key(%s, 'second')", (pid,), jwt_sub=uid)


def reserve():
    return call("anon", "select public.reserve_quota(%s, %s, 'x')", (key, str(uuid.uuid4())))


before = grants()
check(ingest() == "ok" and start_login() == "ok" and new_key() == "ok", "before: ingest, sign-in and new keys work")
check(reserve() != "42501", "before: the relay's metering function is callable (it may still refuse for other reasons)")

run_file("switches_off.sql")
check(ingest() == "42501", "ingest is refused after the switch")
check(start_login() == "42501", "CLI sign-in is refused after the switch")
check(new_key() == "42501", "new API keys are refused after the switch")
check(reserve() == "42501", "the relay's metering is refused after the switch")
check(grants() != before, "the grants really changed")

run_file("switches_on.sql")
check(ingest() == "ok" and start_login() == "ok" and new_key() == "ok", "after switching back on, all three work again")
check(grants() == before, "the grants are IDENTICAL to what they were before the drill")

run_file("revoke_all_api_keys.sql")
cur.execute("select count(*) from public.project_api_keys where revoked_at is null")
check(cur.fetchone()[0] == 0, "revoke_all_api_keys.sql leaves no active key")
check(call("anon", "select public.ingest_event(%s, %s::jsonb)", (key, "{}")) == "PT401", "a revoked key is refused (PT401)")

print("FAILED: " + "; ".join(failures) if failures else "ALL SWITCH CHECKS PASSED")
sys.exit(1 if failures else 0)
