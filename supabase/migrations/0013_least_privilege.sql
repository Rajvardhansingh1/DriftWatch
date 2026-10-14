-- 0013: privileges that match the policies, and deny-by-default for everything created from now on.
--
-- Found by the launch-gate review (Plan 9): Supabase grants every new table and function to anon and authenticated by
-- default, and only some migrations took that back. On the live project `anon` (the public key) still held ALL table
-- privileges, TRUNCATE included, on profiles, organizations and organization_members, and signed-in users held write and
-- TRUNCATE rights on tables whose policies allow only reads. Row-level security blocked every normal request and PostgREST
-- cannot issue TRUNCATE, so nothing was reachable through the API, but privileges should not depend on policies alone.
--
-- After this migration: anon has no table privileges at all (it only calls the allow-listed functions), and authenticated has
-- exactly the verbs that a policy on that table can grant. Writes everywhere else go through definer functions.
-- project_api_keys keeps its column-level SELECT grant (key_hash is never readable) and is not touched here.

-- anon: nothing
revoke all on public.audit_events, public.connected_models, public.connected_probes, public.organization_members,
  public.organizations, public.profiles, public.projects, public.signal_hourly, public.signal_records from anon;

-- authenticated: start from nothing, then give back only what the policies use
revoke all on public.audit_events, public.connected_models, public.connected_probes, public.organization_members,
  public.organizations, public.profiles, public.projects, public.signal_hourly, public.signal_records from authenticated;

grant select on public.audit_events, public.connected_models, public.connected_probes, public.signal_hourly to authenticated;
grant select, update, delete on public.organization_members to authenticated;  -- policies: select, update (admin), delete (admin or self)
grant select, update, delete on public.organizations to authenticated;         -- policies: select, update (owner), delete (owner)
grant select, update on public.profiles to authenticated;                      -- policies: select own, update own
grant select, delete on public.projects to authenticated;                      -- policies: select, delete (owner)
grant update (name, settings) on public.projects to authenticated;             -- column-level on purpose: a client can rename a project, never move it between organizations
grant select, delete on public.signal_records to authenticated;                -- policies: select, delete (admin); inserts only through ingest_event

-- Deny by default from now on: a table or function created by a later migration gets NO rights until that migration grants
-- them explicitly (every migration already does). This is what would have prevented the runner-function gap fixed in 0012.
alter default privileges in schema public revoke all on tables from anon, authenticated;
alter default privileges in schema public revoke all on sequences from anon, authenticated;
alter default privileges in schema public revoke execute on functions from anon, authenticated;
alter default privileges revoke execute on functions from public;  -- Postgres also grants new functions to PUBLIC by default

-- Direct inserts into signal_records are closed. Events enter only through ingest_event (size limits, rate limits, a daily cap,
-- idempotency, a validated envelope); a member who could insert rows directly skipped all of that. The legacy Render route
-- that used this path (POST /v1/events) is removed in the same change; nothing else used it.
drop policy if exists "signal_records_insert_member" on public.signal_records;
revoke insert on public.signal_records from authenticated;
