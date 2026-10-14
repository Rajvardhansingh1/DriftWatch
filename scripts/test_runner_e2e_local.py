"""End to end on a scratch Postgres: the REAL runner against the REAL migration (needs the pgserver venv).

    python scripts/test_runner_e2e_local.py

1. A user connects a model: the key is sealed with the runner's PUBLIC key and stored through connect_model.
2. The runner (real Runner class, a fake provider, the hash embedder) claims the job, opens the key, asks the probes and
   writes signals through the real database functions, as the `anon` role with the runner secret.
3. Checks: signals stored with mode cloud_probe; the job is rescheduled; vectors saved; one decrypt audit row; and the
   evidence for "separation": the plaintext provider key and the answers appear NOWHERE in a dump of every table, and
   not in the runner's output.
Exit code 1 on any failure.
"""
import base64
import contextlib
import io
import json
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
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

from driftwatch_llm.core.embedding import make_embedder  # noqa: E402
from monitor.cloud import seal  # noqa: E402
from monitor.cloud.runner import Runner  # noqa: E402

PROVIDER_KEY = "gsk_" + "E2E" * 14
ANSWER = "THE-ANSWER-TEXT-4471"
PRIVATE, PUBLIC = seal.generate_keypair()
failures: list[str] = []


def check(ok: bool, name: str) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        failures.append(name)


# -- setup ------------------------------------------------------------------------------------------------------
cur.execute("update private.runner_policy set enabled = true, runner_secret_hash = extensions.digest('runner-secret', 'sha256')")
uid = str(uuid.uuid4())
cur.execute("insert into auth.users (id, email, email_confirmed_at) values (%s, 'u@t.local', now())", (uid,))
cur.execute("set role authenticated")
cur.execute("select set_config('request.jwt.claims', %s, false)", ('{"sub":"%s","role":"authenticated"}' % uid,))
cur.execute("select (public.create_project('P')).id")
project = cur.fetchone()[0]
model_id = str(uuid.uuid4())
box = seal.seal(PROVIDER_KEY, model_id, 1, PUBLIC)
cur.execute(
    "select public.connect_model(%s, %s, 'groq', 'some-model', %s, 1, %s, %s, %s)",
    (project, model_id, PROVIDER_KEY[-4:], box["ephemeral"], box["nonce"], box["ciphertext"]),
)
probes = [
    {"prompt": "What is 2+2? Just the number.", "expected": "4", "match_type": "contains"},
    {"prompt": "Capital of France?", "expected": "Paris", "match_type": "exact"},
    {"prompt": "Say OK.", "expected": "OK", "match_type": "contains"},
]
cur.execute("select public.set_probes(%s, %s::jsonb)", (project, json.dumps(probes)))
cur.execute("reset role")


class DbApi:
    """The runner's interface, implemented with the real database functions as the anon role."""

    def __init__(self) -> None:
        self.c = psycopg2.connect(srv.get_uri())
        self.c.autocommit = True
        self.k = self.c.cursor()
        self.k.execute("set role anon")

    def _fn(self, sql: str, *args):
        self.k.execute(sql, args)
        return self.k.fetchone()[0]

    def claim(self):
        return self._fn("select public.runner_claim_jobs('runner-secret')")

    def get_secret(self, m, lease):
        return self._fn("select public.runner_get_secret('runner-secret', %s, %s)", m, lease)

    def get_vectors(self, m, lease):
        return self._fn("select public.runner_get_vectors('runner-secret', %s, %s)", m, lease)

    def save_vectors(self, m, lease, baseline, recent, runs):
        self._fn("select public.runner_save_vectors('runner-secret', %s, %s, %s, %s, %s)", m, lease, baseline, recent, runs)

    def write_signals(self, m, lease, events):
        return self._fn("select public.runner_write_signals('runner-secret', %s, %s, %s::jsonb)", m, lease, json.dumps(events))

    def finish(self, m, lease, outcome, calls):
        self._fn("select public.runner_finish_job('runner-secret', %s, %s, %s, %s)", m, lease, outcome, calls)


answers = {probes[0]["prompt"]: f"4 {ANSWER}", probes[1]["prompt"]: "Paris", probes[2]["prompt"]: "OK"}


def provider(prov, key, model, system, prompt, temperature=0.0, **_):
    assert key == PROVIDER_KEY, "the runner must have opened the real key"
    return answers.get(prompt, f"a sampled answer {temperature} {ANSWER}")


runner = Runner(DbApi(), PRIVATE, embedder=make_embedder("hash"), complete=provider)
out = io.StringIO()
with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
    summary = runner.run_once()
print(out.getvalue()); check(summary == {"jobs": 1, "ok": 1, "failed": 0}, "the runner claimed one job and finished it ok")

cur.execute("select signal, value, meta from public.signal_records where project_id = %s order by signal", (project,))
rows = cur.fetchall()
signals = {r[0]: r for r in rows}
check(set(signals) == {"canary_accuracy", "combined_score", "self_consistency"}, "canary, self-consistency and combined were stored")
check(all(r[2].get("mode") == "cloud_probe" and r[2].get("source") == "cloud_runner" for r in rows), "every row says cloud_probe from cloud_runner")
check(signals["canary_accuracy"][1] == 1.0, "canary accuracy is 1.0 for correct answers")
cur.execute("select state, attempts, due_at > now() + interval '55 minutes' from private.connected_jobs")
state = cur.fetchone()
check(state == ("idle", 0, True), "the job is idle and scheduled one interval ahead")
cur.execute("select runs, baseline is not null, recent is not null from private.probe_vectors")
check(cur.fetchone() == (1, True, True), "vectors were saved after one run")
cur.execute("select action, count(*) from private.runner_audit group by action order by action")
check(dict(cur.fetchall()) == {"claim": 1, "decrypt": 1}, "one claim and one decrypt were audited")
cur.execute("select calls_this_month, last_run_at is not null, last_error from public.connected_models")
check(cur.fetchone() == (5, True, None), "five provider calls were counted and no error is shown")

# separation: nothing readable in a dump of every table, and nothing in the runner's output
needles = [PROVIDER_KEY.encode(), ANSWER.encode(), PRIVATE.encode()]
leaks = []
cur.execute("select table_schema, table_name from information_schema.tables where table_schema in ('public', 'private') and table_type = 'BASE TABLE'")
for schema, table in cur.fetchall():
    cur.execute(f'select t::text from {schema}."{table}" t')
    blob = "\n".join(r[0] for r in cur.fetchall()).encode()
    cur.execute(f'select coalesce(string_agg(encode(convert_to(t::text, \'utf8\'), \'escape\'), \'\'), \'\') from {schema}."{table}" t')
    escaped = cur.fetchone()[0].encode()
    for needle in needles:
        if needle in blob or needle in escaped:
            leaks.append((schema, table, needle[:6]))
check(not leaks, f"the provider key, the answers and the private key are in no table ({leaks})")
cur.execute("select ciphertext from private.connected_secrets")
check(PROVIDER_KEY.encode() not in bytes(cur.fetchone()[0]), "the stored ciphertext does not contain the key")
check(not any(n.decode() in out.getvalue() for n in needles), "the runner's output holds no key, answer or private key")
check("outcome=ok" in out.getvalue(), "the runner reported the job")

# a second pass right away finds nothing due
second = io.StringIO()
with contextlib.redirect_stdout(second):
    again = runner.run_once()
check(again["jobs"] == 0, "nothing is due right after a good run")

print("FAILED: " + "; ".join(failures) if failures else "ALL RUNNER END-TO-END CHECKS PASSED")
sys.exit(1 if failures else 0)
