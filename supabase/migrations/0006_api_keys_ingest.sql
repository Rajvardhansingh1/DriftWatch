-- 0006: write-only project API keys and the canonical ingest path.
-- Validation lives here once. The agent calls ingest_event() through PostgREST;
-- the API key identifies the project, so a client can never choose one.
-- Lock order inside ingest_event is always: ingest_rate, project_daily_rows,
-- project_api_keys, signal_records. A fixed order means concurrent calls queue
-- but cannot deadlock.

create extension if not exists pgcrypto with schema extensions;

create table public.project_api_keys (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects (id) on delete cascade,
  name text not null check (char_length(name) between 1 and 64),
  prefix text not null unique,
  key_hash bytea not null,
  created_by uuid not null references public.profiles (id),
  created_at timestamptz not null default now(),
  last_used_at timestamptz,
  revoked_at timestamptz
);
create index project_api_keys_project_idx on public.project_api_keys (project_id);
create index project_api_keys_created_by_idx on public.project_api_keys (created_by);

alter table public.project_api_keys enable row level security;
revoke all on public.project_api_keys from anon, authenticated;
-- Metadata only. key_hash is never readable by any client role.
grant select (id, project_id, name, prefix, created_at, last_used_at, revoked_at)
  on public.project_api_keys to authenticated;
create policy "api_keys_select_admin" on public.project_api_keys
  for select using (private.is_project_member(project_id, 'admin'));
-- No client insert/update/delete: the RPCs below are the only write path.

create table private.ingest_rate (
  key_id uuid not null,
  bucket timestamptz not null,
  n integer not null,
  primary key (key_id, bucket)
);
create table private.project_daily_rows (
  project_id uuid not null,
  day date not null,
  n integer not null,
  primary key (project_id, day)
);
revoke all on private.ingest_rate, private.project_daily_rows from public, anon, authenticated;

create function public.create_project_api_key(p_project_id uuid, p_name text)
returns text
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_prefix text;
  v_secret text;
  v_org uuid;
begin
  if (select auth.uid()) is null then
    raise exception 'authentication required' using errcode = 'PT401';
  end if;
  if not exists (
    select 1 from auth.users where id = (select auth.uid()) and email_confirmed_at is not null
  ) then
    raise exception 'verify your email first' using errcode = 'PT403';
  end if;
  if not private.is_project_member(p_project_id, 'admin') then
    raise exception 'forbidden' using errcode = 'PT403';
  end if;
  if (select count(*) from public.project_api_keys
      where project_id = p_project_id and revoked_at is null) >= 10 then
    raise exception 'key limit reached' using errcode = 'PT422';
  end if;

  select organization_id into v_org from public.projects where id = p_project_id;
  v_prefix := 'dw_' || encode(extensions.gen_random_bytes(5), 'hex');
  v_secret := encode(extensions.gen_random_bytes(32), 'hex');

  insert into public.project_api_keys (project_id, name, prefix, key_hash, created_by)
  values (p_project_id, p_name, v_prefix,
          extensions.digest(v_secret, 'sha256'), (select auth.uid()));

  perform private.write_audit((select auth.uid()), v_org, 'api_key.create', p_project_id::text, 'ok');
  return v_prefix || '_' || v_secret;
end;
$$;
revoke all on function public.create_project_api_key(uuid, text) from public, anon;
grant execute on function public.create_project_api_key(uuid, text) to authenticated;

create function public.revoke_project_api_key(p_key_id uuid)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_project uuid;
  v_org uuid;
begin
  select k.project_id, p.organization_id into v_project, v_org
  from public.project_api_keys k join public.projects p on p.id = k.project_id
  where k.id = p_key_id;
  if v_project is null or not private.is_project_member(v_project, 'admin') then
    raise exception 'forbidden' using errcode = 'PT403';
  end if;
  update public.project_api_keys set revoked_at = now()
  where id = p_key_id and revoked_at is null;
  perform private.write_audit((select auth.uid()), v_org, 'api_key.revoke', p_key_id::text, 'ok');
end;
$$;
revoke all on function public.revoke_project_api_key(uuid) from public, anon;
grant execute on function public.revoke_project_api_key(uuid) to authenticated;

create function public.ingest_event(p_api_key text, p_event jsonb)
returns text
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_key public.project_api_keys;
  v_hits integer;
  v_day_rows integer;
  v_event_id uuid;
  v_signal text;
  v_value double precision;
  v_occurred timestamptz;
  v_meta jsonb;
  v_source text;
  v_ts text;
begin
  -- 1. Authenticate. Same error for malformed, unknown and revoked keys.
  if p_api_key is null or p_api_key !~ '^dw_[0-9a-f]{10}_[0-9a-f]{64}$' then
    raise exception 'unauthorized' using errcode = 'PT401';
  end if;
  select * into v_key from public.project_api_keys
    where prefix = substr(p_api_key, 1, 13) and revoked_at is null;
  if not found or v_key.key_hash <> extensions.digest(substr(p_api_key, 15), 'sha256') then
    raise exception 'unauthorized' using errcode = 'PT401';
  end if;

  -- 2. Rate limits: per key per minute, and per project per day.
  insert into private.ingest_rate (key_id, bucket, n)
    values (v_key.id, date_trunc('minute', now()), 1)
    on conflict (key_id, bucket) do update set n = private.ingest_rate.n + 1
    returning n into v_hits;
  if v_hits > 600 then
    raise exception 'rate limited' using errcode = 'PT429';
  end if;
  insert into private.project_daily_rows (project_id, day, n)
    values (v_key.project_id, current_date, 1)
    on conflict (project_id, day) do update set n = private.project_daily_rows.n + 1
    returning n into v_day_rows;
  if v_day_rows > 50000 then
    raise exception 'daily limit reached' using errcode = 'PT429';
  end if;

  -- 3. Validate the envelope (mirrors schemas/event.v1.json and monitor/cloud/ingest.py).
  if p_event is null or jsonb_typeof(p_event) <> 'object' or pg_column_size(p_event) > 8192 then
    raise exception 'invalid event' using errcode = 'PT422';
  end if;
  if exists (
    select 1 from jsonb_object_keys(p_event) k
    where k not in ('schema_version', 'event_id', 'occurred_at', 'source', 'signal', 'value',
                    'meta', 'content_capture', 'organization_id', 'project_id', 'environment',
                    'runtime_id', 'model_provider', 'model_name', 'request_id', 'received_at')
  ) then
    raise exception 'unknown field' using errcode = 'PT422';
  end if;
  if (p_event ->> 'schema_version') is distinct from '1' then
    raise exception 'unsupported schema_version' using errcode = 'PT422';
  end if;

  begin
    v_event_id := (p_event ->> 'event_id')::uuid;
  exception when others then
    raise exception 'event_id must be a uuid' using errcode = 'PT422';
  end;

  v_ts := p_event ->> 'occurred_at';
  if v_ts is null or v_ts !~ '(Z|[+-][0-9]{2}:?[0-9]{2})$' then
    raise exception 'occurred_at needs a timezone' using errcode = 'PT422';
  end if;
  begin
    v_occurred := v_ts::timestamptz;
  exception when others then
    raise exception 'occurred_at invalid' using errcode = 'PT422';
  end;

  v_signal := p_event ->> 'signal';
  if v_signal is null or v_signal not in ('embedding_drift', 'self_consistency', 'canary_accuracy',
                                          'judge_trend', 'hallucination_score', 'combined_score') then
    raise exception 'unknown signal' using errcode = 'PT422';
  end if;

  if jsonb_typeof(p_event -> 'value') is distinct from 'number' then
    raise exception 'value must be a number' using errcode = 'PT422';
  end if;
  v_value := (p_event ->> 'value')::double precision;
  if abs(v_value) >= 1e9 then
    raise exception 'value out of range' using errcode = 'PT422';
  end if;

  v_source := p_event ->> 'source';
  if v_source is null or char_length(v_source) = 0 or char_length(v_source) > 128 then
    raise exception 'invalid source' using errcode = 'PT422';
  end if;

  -- Size and key count are the server guarantee. Nesting depth is checked
  -- client-side only (monitor/cloud/ingest.py); the size cap bounds it here.
  v_meta := coalesce(p_event -> 'meta', '{}'::jsonb);
  if jsonb_typeof(v_meta) <> 'object' or pg_column_size(v_meta) > 4096
     or (select count(*) from jsonb_object_keys(v_meta)) > 32 then
    raise exception 'invalid meta' using errcode = 'PT422';
  end if;

  -- 4. Touch last_used_at (at most once a minute) BEFORE the insert, because
  -- PL/pgSQL FOUND reflects only the most recent SQL command.
  if (v_key.last_used_at is null or v_key.last_used_at < now() - interval '1 minute') then
    update public.project_api_keys set last_used_at = now() where id = v_key.id;
  end if;

  -- 5. Insert once. The unique (project_id, event_id) makes retries safe.
  insert into public.signal_records (project_id, event_id, signal, value, meta, occurred_at)
  values (v_key.project_id, v_event_id, v_signal, v_value,
          v_meta || jsonb_build_object('source', v_source), v_occurred)
  on conflict (project_id, event_id) do nothing;

  if not found then
    return 'duplicate';
  end if;
  return 'accepted';
end;
$$;
revoke all on function public.ingest_event(text, jsonb) from public;
grant execute on function public.ingest_event(text, jsonb) to anon, authenticated;
