-- KILL SWITCHES: stop a part of the platform by taking away the right to call its function. Reversible with switches_on.sql.
-- Run only the line(s) you need, in the Supabase SQL editor. Rehearsed by scripts/test_switches_local.py.
--
-- What the callers see: a refused call. The agent treats it as a temporary problem, keeps its events on disk and retries
-- with backoff, so switching ingest off loses nothing. The CLI shows a plain "DriftWatch had a problem" message.

-- A. INGEST: no new scores are accepted (agents queue and retry; the cloud runner's writes are separate).
revoke execute on function public.ingest_event(text, jsonb) from anon, authenticated;

-- B. CLI SIGN-IN: nobody can start a new `driftwatch init` / `driftwatch login`.
revoke execute on function public.start_device_login(text, text) from anon, authenticated;

-- C. NEW API KEYS: nobody can create one (existing keys keep working; see A to stop those too).
revoke execute on function public.create_project_api_key(uuid, text) from authenticated;

-- D. FREE ALLOWANCE RELAY: the metering functions the relay needs (so /v1/judge answers "not available").
revoke execute on function public.reserve_quota(text, uuid, text) from anon, authenticated;
revoke execute on function public.settle_quota(text, uuid, text, text) from anon, authenticated;
