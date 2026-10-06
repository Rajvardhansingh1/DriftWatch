-- 0007: bounded growth (30-day raw + permanent hourly rollup), live updates, keep-alive.

create extension if not exists pg_cron;

create table public.signal_hourly (
  project_id uuid not null references public.projects (id) on delete cascade,
  signal text not null,
  hour timestamptz not null,
  n integer not null,
  avg_value double precision not null,
  max_value double precision not null,
  primary key (project_id, signal, hour)
);
alter table public.signal_hourly enable row level security;
revoke all on public.signal_hourly from anon;
create policy "signal_hourly_select_member" on public.signal_hourly
  for select using (private.is_project_member(project_id, 'viewer'));
grant select on public.signal_hourly to authenticated;

create function private.rollup_and_prune() returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
  -- Recompute only WHOLE hours that are still fully retained (1 hour to 29 days
  -- old). Re-running is idempotent, and a missed day is caught up next run.
  insert into public.signal_hourly (project_id, signal, hour, n, avg_value, max_value)
  select project_id, signal, date_trunc('hour', occurred_at), count(*), avg(value), max(value)
  from public.signal_records
  where occurred_at >= date_trunc('hour', now() - interval '29 days')
    and occurred_at <  date_trunc('hour', now() - interval '1 hour')
    and legacy_signal_id is null
  group by project_id, signal, date_trunc('hour', occurred_at)
  on conflict (project_id, signal, hour) do update
    set n = excluded.n, avg_value = excluded.avg_value, max_value = excluded.max_value;

  delete from public.signal_records
  where occurred_at < now() - interval '30 days' and legacy_signal_id is null;

  delete from private.ingest_rate where bucket < now() - interval '2 hours';
  delete from private.project_daily_rows where day < current_date - 2;
end;
$$;
revoke all on function private.rollup_and_prune() from public, anon, authenticated;

select cron.schedule('driftwatch-rollup-prune', '17 3 * * *', 'select private.rollup_and_prune()');

-- Live dashboard updates. RLS still applies to Realtime subscribers.
alter publication supabase_realtime add table public.signal_records;

-- Keep-alive target: a trivial call that still reaches the database.
create function public.ping() returns text
language sql
stable
set search_path = ''
as $$ select 'ok'::text $$;
revoke all on function public.ping() from public;
grant execute on function public.ping() to anon, authenticated;
