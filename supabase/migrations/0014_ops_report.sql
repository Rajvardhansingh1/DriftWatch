-- 0014: a small operations report for the daily keep-alive workflow: how big the database is against the free-plan limit.
-- Aggregates only (sizes and counts, no ids, no content). Gated by the runner secret, like runner_health, and closed to
-- signed-in users, so it is not another public function. Fails closed while no secret hash is configured.

create function public.ops_report(p_secret text)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
begin
  perform private.require_runner(p_secret);
  return jsonb_build_object(
    'database_bytes', pg_database_size(current_database()),
    'signal_records', (select count(*) from public.signal_records),
    'projects', (select count(*) from public.projects),
    'users', (select count(*) from public.profiles),
    'api_keys_active', (select count(*) from public.project_api_keys where revoked_at is null),
    'usage_today', coalesce((select used from private.usage_daily where day = current_date), 0)
  );
end;
$$;
revoke all on function public.ops_report(text) from public, anon, authenticated;
grant execute on function public.ops_report(text) to anon;
