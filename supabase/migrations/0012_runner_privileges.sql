-- 0012: close two gaps the Supabase advisors and a stricter test found in 0011 (applied live already, so fixed forward).
--
-- 1. Supabase grants EXECUTE on every new function to the API roles by default. 0011 revoked the
--    functions from PUBLIC and granted the runner's functions to anon, but never revoked them from `authenticated`, so a
--    signed-in user could call them. They still failed without the runner secret, but the runner is the only legitimate
--    caller and nobody else should be able to reach them at all.
-- 2. connected_models.created_by is a foreign key without an index (performance advisor).

revoke execute on function public.runner_claim_jobs(text) from authenticated;
revoke execute on function public.runner_get_secret(text, uuid, uuid) from authenticated;
revoke execute on function public.runner_get_vectors(text, uuid, uuid) from authenticated;
revoke execute on function public.runner_save_vectors(text, uuid, uuid, text, text, integer) from authenticated;
revoke execute on function public.runner_write_signals(text, uuid, uuid, jsonb) from authenticated;
revoke execute on function public.runner_finish_job(text, uuid, uuid, text, integer) from authenticated;
revoke execute on function public.runner_health(text) from authenticated;

create index if not exists connected_models_created_by_idx on public.connected_models (created_by);
