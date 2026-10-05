# DriftWatch threat model and security controls

Scope: the monitor API (`monitor/`), cloud auth and ingestion (`monitor/cloud/`, `supabase/`), sync outbox (`monitor/sync/`), evaluator runners (`monitor/plugins/`), frontend (`frontend/`).

## Assets

- Tenant data in Supabase (`organizations`, `projects`, `signal_records`).
- Provider API keys (`GROQ_API_KEY`, `GOOGLE_API_KEY`) and BYOK keys.
- Supabase JWT secret (`SUPABASE_JWT_SECRET`). Used server-side only.
- Platform-operator allowlist (`PLATFORM_ADMIN_USER_IDS`).

## Threats and controls

| Threat | Control | Where | Status |
|---|---|---|---|
| Tenant escape (read other org's rows) | RLS on every table; `private.is_org_member` / `is_project_member` helpers; cross-tenant SQL test | `supabase/migrations/0001–0003`, `supabase/tests/0001_cross_tenant_isolation.sql` | Verified live (user B sees 0 rows). Automated re-run in CI not possible without a DB |
| Public RPC abuse of helpers | Helpers moved to non-exposed `private` schema; trigger-only function revoked from API roles | `0002` | Verified via advisors. `create_organization` is intentionally public and self-checks `auth.uid()` |
| Forged or expired token | HS256 signature + `aud=authenticated` + `exp` check | `monitor/cloud/auth.py` | Unit tested |
| Privilege via email/metadata | Platform admin is an explicit env allowlist; org roles don't grant it | `monitor/admin/access.py` | Unit tested (admin-looking email gets 403) |
| Self-assigned org role | No client INSERT on `organizations` / `organization_members`; creation via RPC only | `0001` | Policy-level; verified by the live test |
| Replayed or duplicate events | Unique `(project_id, event_id)` constraint (409 → "duplicate") | `0004`, `monitor/cloud/supabase_store.py` | Mock-tested. Live constraint not exercised |
| Oversized or malformed payloads | Strict schema, unknown fields rejected, meta ≤ 4 KB, query text ≤ 500 chars | `monitor/cloud/ingest.py`, `monitor/main.py` | Unit tested |
| Secret leakage in logs | Redaction filter for Bearer, JWT, Groq/Google/OpenAI-style keys, DB URLs | `monitor/logging_redaction.py` | Unit tested. Filter must be installed (`redaction.install()`) at startup. Not yet wired into `main.py` |
| Secret leakage to evaluators | Environment scrubbed of secret-named variables | `monitor/plugins/runner.py` | Unit tested |
| Malicious evaluator code | Process runner only (scrubbed env, timeout, output cap). Not isolation. Cloud plugin execution disabled | `monitor/plugins/runner.py` | Process-level only. Container isolation (spec 11.2) is NOT provided: Render and Vercel don't run Docker inside the service. Needs a separate isolated worker host before enabling cloud plugins |
| Quota abuse / provider spend | Per-session slowapi limit, internal shared limiter, daily quota, `DRIFTWATCH_FORCE_SIMULATED` for smoke tests | `monitor/main.py`, `monitor/rate_limit.py`, `monitor/quota.py` | Tested; quotas are in-process, not durable across instances (known gap) |
| Destructive admin error | Admin status is read-only; no admin write routes exist | `monitor/admin/routes.py` | Read-only by construction |
| Vendored code drift | Hallucination scorer is a vendored copy of Project 1's; must be updated by hand | `monitor/signals/hallucination_scorer.py`, D-012 | Manual process |
| Supply chain | Dependencies pinned loosely in `requirements.txt`; npm audit has one accepted build-time advisory | `requirements.txt`, `frontend/package.json`, D-014 | No lockfile pin for Python. Not scanned in CI |

## Known gaps (not closed)

- Quotas and rate limits are in-process. Multi-instance enforcement needs the durable `usage_ledger` (not built).
- Admin audit events are only logged; the `audit_events` table (migration 0004) is not written by the server yet.
- Cloud user identity is verified, but there is no per-device runtime credential. The local sync outbox has no authenticated uplink yet.
- No backup/restore drill has been executed.
- No penetration test has been performed.
- Frontend auth pages depend on Supabase's built-in session storage. Not reviewed for XSS beyond React defaults.

## Reporting

Report suspected vulnerabilities to the project owner directly. Do not open a public issue with exploit details.
