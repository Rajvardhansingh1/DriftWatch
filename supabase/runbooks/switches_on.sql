-- Puts back exactly the rights that switches_off.sql took away (the same grants the migrations made).
-- Rehearsed by scripts/test_switches_local.py, which compares the grants before and after.

grant execute on function public.ingest_event(text, jsonb) to anon, authenticated;
grant execute on function public.start_device_login(text, text) to anon, authenticated;
grant execute on function public.create_project_api_key(uuid, text) to authenticated;
grant execute on function public.reserve_quota(text, uuid, text) to anon, authenticated;
grant execute on function public.settle_quota(text, uuid, text, text) to anon, authenticated;
