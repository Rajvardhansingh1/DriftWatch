# Independent review packet

For a reviewer who has not seen DriftWatch. Please report findings as: location, what an attacker can do, how you would fix it.
Do not test against the production project; the SQL tests run on a scratch Postgres (`python scripts/run_sql_tests_local.py`).

## What it is

An LLM drift monitor. A local agent measures drift on the user's machine and sends only numbers. Cloud pieces: Supabase (auth,
Postgres with RLS and SECURITY DEFINER functions), a Next.js site on Vercel, a small FastAPI service on Render (demo and the
free-allowance relay), and an optional scheduled GitHub Actions runner ("cloud connect") that opens sealed provider keys.

## Trust boundaries to attack

1. **Browser -> Supabase** with a user JWT. Anything a signed-in user can read or write. Start at `supabase/migrations/0013_least_privilege.sql`
   and `supabase/tests/0007_remaining_surface.sql`.
2. **Agent / curl -> `ingest_event`** with a project API key (no JWT). Can one key touch another project, exceed limits, or read?
   `supabase/migrations/` (ingest), tests `0002_api_keys_ingest.sql`.
3. **Anonymous RPCs.** The 13 allow-listed in `tests/test_repo_hygiene.py`; each must fail closed without its secret.
4. **Runner -> `runner_*` functions** with the runner secret; leases, `skip locked`, sealed keys (X25519 + HKDF + AES-GCM, AAD binds key
   to model and key id). `supabase/migrations/0011_connected_models.sql`, `monitor/cloud/seal.py`, `driftwatch_llm/runner.py`.
5. **Relay `/v1/judge`.** Cannot choose prompt, model or destination; quota is atomic. `monitor/cloud/llm_proxy.py`, `supabase/tests/0005_usage_quota.sql`.
6. **Local agent.** IPC (mutual HMAC), dashboard on 127.0.0.1 (token fragment -> cookie, Host allow-list). `driftwatch_llm/agent/`.
7. **Supply chain.** `.github/workflows/*`, `requirements-runner.txt`, release provenance.

## Evidence already collected

`deploy/LAUNCH_GATES.md` (every risk -> the test that covers it), `deploy/ADVISOR_NOTES.md` (what the Supabase advisor reports and why
it is accepted), `SECURITY.md`, `deploy/RUNBOOK_INCIDENTS.md`.

## Known and accepted

The advisor's "anonymous can execute definer function" warnings for the allow-listed set; INFO-level `rls_enabled_no_policy` on `private`
tables (intentional: no client access at all); npm audit leftovers listed with expiry in `deploy/audit-exceptions.json`.
