"""Local check that 100 concurrent reserve_quota calls never exceed a cap (needs the throwaway pgserver venv).

    python scripts/test_quota_concurrency_local.py

Builds the same Supabase shim as run_sql_tests_local.py, applies the migrations, then runs 100 threads (each its own
connection) against a cap of 10 for one user and against a daily budget of 25 across several users. Exit code 1 on failure.
"""
import re
import sys
import threading
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
src = (REPO / "scripts" / "run_sql_tests_local.py").read_text(encoding="utf-8")
head = src[: src.index("failed = 0")]
head = head.replace("REPO = Path(__file__).resolve().parent.parent", f"REPO = Path(r'{REPO}')")
head = head.replace("UPTO = int(sys.argv[1]) if len(sys.argv) > 1 else 99", "UPTO = 99").replace("ONLY_TESTS = sys.argv[2:]", "ONLY_TESTS = []")
ns: dict = {}
exec(compile(head, "runner_head", "exec"), ns)
srv, conn = ns["srv"], ns["conn"]
conn.autocommit = True
cur = conn.cursor()

import psycopg2  # noqa: E402

cur.execute("update private.quota_policies set relay_secret_hash = extensions.digest('relay-secret', 'sha256') where name = 'free'")
users = []
for i in range(5):
    uid = str(uuid.uuid4())
    cur.execute("insert into auth.users (id, email, email_confirmed_at) values (%s, %s, now())", (uid, f"u{i}@t.local"))
    users.append(uid)
keys = []
for uid in users:
    cur.execute("set role authenticated")
    cur.execute("select set_config('request.jwt.claims', %s, false)", ('{"sub":"%s","role":"authenticated"}' % uid,))
    cur.execute("select (public.create_project('P')).id")
    pid = cur.fetchone()[0]
    cur.execute("select public.create_project_api_key(%s, 'k')", (pid,))
    keys.append(cur.fetchone()[0])
    cur.execute("reset role")

failures = []


WORKERS = 40  # the embedded Postgres allows 100 connections; 40 connections make the 100 calls overlap heavily


def storm(key_for, n, label):
    """n reserve calls spread over WORKERS connections that all start together."""
    results = {"ok": 0, "refused": 0, "other": []}
    lock = threading.Lock()
    barrier = threading.Barrier(WORKERS)
    todo = list(range(n))

    def worker(w):
        c = psycopg2.connect(srv.get_uri())
        c.autocommit = True
        k = c.cursor()
        k.execute("set role anon")
        barrier.wait()
        for i in todo[w::WORKERS]:
            try:
                k.execute("select public.reserve_quota(%s, %s, %s)", (key_for(i), str(uuid.uuid4()), "relay-secret"))
                with lock:
                    results["ok"] += 1
            except psycopg2.Error as e:
                with lock:
                    if e.pgcode in ("PT429", "PT503"):
                        results["refused"] += 1
                    else:
                        results["other"].append(repr(e)[:120])
        c.close()

    threads = [threading.Thread(target=worker, args=(w,)) for w in range(WORKERS)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    print(f"{label}: {results}")
    return results


# 1. one user, cap 10, 100 callers (two keys of the same user would share it; one key is enough)
cur.execute("update private.quota_policies set per_user_cap = 10, global_daily_cap = 1000 where name = 'free'")
r = storm(lambda i: keys[0], 100, "one user, cap 10")
cur.execute("select used from private.usage_totals where user_id = %s", (users[0],))
used = cur.fetchone()[0]
cur.execute("select count(*) from private.usage_ledger where user_id = %s and state = 'reserved'", (users[0],))
reserved = cur.fetchone()[0]
if not (r["ok"] == 10 and r["refused"] == 90 and not r["other"] and used == 10 and reserved == 10):
    failures.append(f"per-user cap broken: {r}, used {used}, ledger {reserved}")

# 2. five users, per-user cap high, daily budget 25 (already 10 used today by user 0), 100 callers
cur.execute("update private.quota_policies set per_user_cap = 1000, global_daily_cap = 25 where name = 'free'")
r = storm(lambda i: keys[1 + i % 4], 100, "four users, daily budget 25 with 10 already used")
cur.execute("select used from private.usage_daily where day = current_date")
day_used = cur.fetchone()[0]
cur.execute("select coalesce(sum(used), 0) from private.usage_totals where user_id <> %s", (users[0],))
others = cur.fetchone()[0]
if not (r["ok"] == 15 and day_used == 25 and others == 15 and not r["other"]):
    failures.append(f"daily budget broken: {r}, day {day_used}, others {others}")

# 3. the same idempotency key from 50 callers counts once
cur.execute("update private.quota_policies set per_user_cap = 1000, global_daily_cap = 1000 where name = 'free'")
same = str(uuid.uuid4())
cur.execute("select used from private.usage_totals where user_id = %s", (users[4],))
before = (cur.fetchone() or [0])[0]
barrier = threading.Barrier(40)


def dup():
    c = psycopg2.connect(srv.get_uri())
    c.autocommit = True
    k = c.cursor()
    k.execute("set role anon")
    barrier.wait()
    k.execute("select public.reserve_quota(%s, %s, %s)", (keys[4], same, "relay-secret"))
    c.close()


ts = [threading.Thread(target=dup) for _ in range(40)]
[t.start() for t in ts]
[t.join() for t in ts]
cur.execute("select used from private.usage_totals where user_id = %s", (users[4],))
after = cur.fetchone()[0]
print(f"same idempotency key x40: counted {after - before}")
if after - before != 1:
    failures.append(f"idempotency broken: counted {after - before}")

print("FAILED: " + "; ".join(failures) if failures else "ALL QUOTA CONCURRENCY CHECKS PASSED")
sys.exit(1 if failures else 0)
