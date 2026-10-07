drop function if exists public.ingest_event(text, jsonb);
drop function if exists public.revoke_project_api_key(uuid);
drop function if exists public.create_project_api_key(uuid, text);
drop table if exists private.project_daily_rows;
drop table if exists private.ingest_rate;
drop table if exists public.project_api_keys;
