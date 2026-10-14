-- EMERGENCY ROLLBACK of 0013: restores the old, broader behaviour. Use only if 0013 broke something you cannot fix forward;
-- the old state let `anon` hold table privileges and let members insert signal rows directly, bypassing ingest_event's limits.
-- Prefer fixing forward with a narrower grant.

-- direct inserts into signal_records (policy and column grants as in 0003 / 0005)
create policy "signal_records_insert_member" on public.signal_records
  for insert with check (private.is_project_member(project_id, 'member'));
grant insert (project_id, event_id, signal, value, meta, occurred_at) on public.signal_records to authenticated;

-- the default privileges are returned to Supabase's defaults
alter default privileges in schema public grant all on tables to anon, authenticated;
alter default privileges in schema public grant all on sequences to anon, authenticated;
alter default privileges in schema public grant execute on functions to anon, authenticated;
alter default privileges grant execute on functions to public;

-- The table privileges are NOT widened again here: if a specific verb is missing, grant just that verb, for example
--   grant update on public.some_table to authenticated;
