select cron.unschedule('driftwatch-rollup-prune');
alter publication supabase_realtime drop table public.signal_records;
drop function if exists public.ping();
drop function if exists private.rollup_and_prune();
drop table if exists public.signal_hourly;
