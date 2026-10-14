"""Local check that concurrent runner_claim_jobs calls never hand one job to two runners (needs the pgserver venv).

    python scripts/test_runner_concurrency_local.py

30 connected models are due. 40 runners (each its own connection) call runner_claim_jobs at the same moment, over and over,
until nothing is left. Every model must be claimed exactly once, with a distinct lease, and nothing may be claimed twice
while leased. Exit code 1 on failure.
"""
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

cur.execute("update private.runner_policy set enabled = true, runner_secret_hash = extensions.digest('runner-secret', 'sha256'), max_models_per_pass = 3")
N = 30
models = set()
for i in range(N):
    uid = str(uuid.uuid4())
    cur.execute("insert into auth.users (id, email, email_confirmed_at) values (%s, %s, now())", (uid, f"u{i}@t.local"))
    cur.execute("set role authenticated")
    cur.execute("select set_config('request.jwt.claims', %s, false)", ('{"sub":"%s","role":"authenticated"}' % uid,))
    cur.execute("select (public.create_project('P')).id")
    pid = cur.fetchone()[0]
    mid = str(uuid.uuid4())
    cur.execute(
        "select public.connect_model(%s, %s, 'groq', 'm', 'abcd', 1, encode(decode(repeat('ab', 32), 'hex'), 'base64'), "
        "encode(decode(repeat('cd', 12), 'hex'), 'base64'), encode(decode(repeat('ef', 40), 'hex'), 'base64'))",
        (pid, mid),
    )
    cur.execute("select public.set_probes(%s, '[{\"prompt\":\"p\",\"expected\":\"e\"},{\"prompt\":\"q\",\"expected\":\"f\"}]'::jsonb)", (pid,))
    cur.execute("reset role")
    models.add(mid)

claims: list[tuple[str, str]] = []
lock = threading.Lock()
WORKERS = 40
barrier = threading.Barrier(WORKERS)
errors: list[str] = []


def worker():
    c = psycopg2.connect(srv.get_uri())
    c.autocommit = True
    k = c.cursor()
    k.execute("set role anon")
    barrier.wait()
    idle = 0
    while idle < 3:
        try:
            k.execute("select public.runner_claim_jobs('runner-secret')")
            got = k.fetchone()[0]
        except psycopg2.Error as e:
            errors.append(repr(e)[:150])
            return
        if not got:
            idle += 1
            continue
        idle = 0
        with lock:
            claims.extend((j["model_id"], j["lease"]) for j in got)
    c.close()


threads = [threading.Thread(target=worker) for _ in range(WORKERS)]
[t.start() for t in threads]
[t.join() for t in threads]

ids = [m for m, _ in claims]
leases = [lease for _, lease in claims]
failures = []
if errors:
    failures.append(f"errors: {errors[:3]}")
if len(ids) != len(set(ids)):
    failures.append(f"a job was claimed twice: {len(ids)} claims for {len(set(ids))} jobs")
if set(ids) != models:
    failures.append(f"claimed {len(set(ids))} of {N} jobs")
if len(leases) != len(set(leases)):
    failures.append("leases are not distinct")
print(f"{len(ids)} claims for {N} due jobs by {WORKERS} runners; distinct jobs {len(set(ids))}; distinct leases {len(set(leases))}")
print("FAILED: " + "; ".join(failures) if failures else "ALL RUNNER CONCURRENCY CHECKS PASSED")
sys.exit(1 if failures else 0)
