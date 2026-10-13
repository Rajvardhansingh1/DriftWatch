"""Rehearses supabase/runbooks/cloud_connect_compromise.sql on a scratch Postgres (needs the pgserver venv).

    python scripts/test_runbook_local.py

Connects two models, runs the runbook, and checks: the runner can no longer do anything, nothing can be connected, every
sealed secret is gone, and step 2 listed exactly the affected users. Exit code 1 on failure.
"""
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


cur.execute("update private.runner_policy set enabled = true, runner_secret_hash = extensions.digest('runner-secret', 'sha256')")
emails = []
for i in range(2):
    uid = str(uuid.uuid4())
    email = f"user{i}@t.local"
    emails.append(email)
    cur.execute("insert into auth.users (id, email, email_confirmed_at) values (%s, %s, now())", (uid, email))
    cur.execute("set role authenticated")
    cur.execute("select set_config('request.jwt.claims', %s, false)", ('{"sub":"%s","role":"authenticated"}' % uid,))
    cur.execute("select (public.create_project('P')).id")
    pid = cur.fetchone()[0]
    cur.execute(
        "select public.connect_model(%s, %s, 'groq', 'm', 'abcd', 1, encode(decode(repeat('ab', 32), 'hex'), 'base64'), "
        "encode(decode(repeat('cd', 12), 'hex'), 'base64'), encode(decode(repeat('ef', 40), 'hex'), 'base64'))",
        (pid, str(uuid.uuid4())),
    )
    cur.execute("select public.set_probes(%s, '[{\"prompt\":\"p\",\"expected\":\"e\"}]'::jsonb)", (pid,))
    cur.execute("reset role")

# run the runbook statement by statement, remembering the step-2 result
sql = (REPO / "supabase" / "runbooks" / "cloud_connect_compromise.sql").read_text(encoding="utf-8")
statements = [s.strip() for s in sql.split(";") if s.strip() and not all(l.strip().startswith("--") or not l.strip() for l in s.splitlines())]
listing, final = None, None
for stmt in statements:
    cur.execute(stmt)
    if stmt.lstrip("- \n").lower().startswith("-- 2.") or "from public.connected_models m" in stmt and stmt.lstrip().lower().startswith(("select", "--")) and "join public.projects" in stmt:
        listing = cur.fetchall()
    elif "secrets_left" in stmt:
        final = cur.fetchone()

check(listing is not None and sorted(r[1] for r in listing) == sorted(emails), "step 2 listed exactly the affected users")
check(final == (0, 0, False), f"step 4: no secrets, no jobs, switch off ({final})")

cur.execute("set role anon")
for fn in ("select public.runner_claim_jobs('runner-secret')", "select public.runner_health('runner-secret')"):
    try:
        cur.execute(fn)
        check(False, f"the runner can still call: {fn[:40]}")
    except Exception as exc:  # noqa: BLE001
        check(getattr(exc, "pgcode", None) == "PT401", "the old runner secret is refused after the runbook")
cur.execute("reset role")
uid = str(uuid.uuid4())
cur.execute("insert into auth.users (id, email, email_confirmed_at) values (%s, 'late@t.local', now())", (uid,))
cur.execute("set role authenticated")
cur.execute("select set_config('request.jwt.claims', %s, false)", ('{"sub":"%s","role":"authenticated"}' % uid,))
cur.execute("select (public.create_project('Q')).id")
pid = cur.fetchone()[0]
try:
    cur.execute(
        "select public.connect_model(%s, %s, 'groq', 'm', 'abcd', 1, encode(decode(repeat('ab', 32), 'hex'), 'base64'), "
        "encode(decode(repeat('cd', 12), 'hex'), 'base64'), encode(decode(repeat('ef', 40), 'hex'), 'base64'))",
        (pid, str(uuid.uuid4())),
    )
    check(False, "a model could still be connected after the runbook")
except Exception as exc:  # noqa: BLE001
    check(getattr(exc, "pgcode", None) == "PT503", "nothing can be connected after the runbook")

print("FAILED: " + "; ".join(failures) if failures else "ALL RUNBOOK CHECKS PASSED")
sys.exit(1 if failures else 0)
