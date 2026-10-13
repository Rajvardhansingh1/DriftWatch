-- 0011: cloud connect. A project can connect ONE model with the user's own provider key; a scheduled runner (GitHub
-- Actions) sends fixed probe prompts to it and writes canary / self-consistency / embedding-drift signals.
--
-- Security model (Plan 7, revision 2):
-- - The provider key is sealed on the web tier with the runner's PUBLIC key (X25519 + HKDF-SHA256 + AES-256-GCM,
--   the model row id as associated data). Only the runner holds the private key, so nothing stored here, on Vercel
--   or on Render can be decrypted without it.
-- - Secrets, jobs, vectors, the audit trail and the runner policy live in the `private` schema: no client role can
--   read or write them. Members see only the model's metadata (provider, model, last4, schedule, last run, last error).
-- - The runner calls definer functions through the public API with a runner secret (sha256 stored in
--   private.runner_policy; unset = everything refused), the same pattern as the relay's secret in 0010.
-- - Ships DARK: private.runner_policy.enabled is false, so nothing can be connected or claimed until the owner flips it.
--
-- Lock order: connected_models -> private.connected_jobs (claim locks jobs only, skip locked).

-- -- policy (singleton) -------------------------------------------------------------------------------------------
create table private.runner_policy (
  id boolean primary key default true check (id),
  enabled boolean not null default false,
  runner_secret_hash bytea,
  max_models_per_pass integer not null default 5 check (max_models_per_pass between 1 and 50),
  max_calls_per_run integer not null default 12 check (max_calls_per_run between 1 and 50),
  lease_minutes integer not null default 10 check (lease_minutes between 1 and 60)
);
insert into private.runner_policy (id) values (true);

-- -- what members can see --------------------------------------------------------------------------------------------
create table public.connected_models (
  id uuid primary key,  -- chosen by the web tier before sealing: it is the associated data of the ciphertext
  project_id uuid not null unique references public.projects (id) on delete cascade,
  provider text not null check (provider in ('groq', 'openai')),
  model text not null check (char_length(model) between 1 and 80 and model ~ '^[A-Za-z0-9][A-Za-z0-9._:/-]*$'),
  last4 text not null check (char_length(last4) = 4),
  interval_minutes integer not null default 60 check (interval_minutes between 15 and 1440),
  monthly_budget integer not null default 2000 check (monthly_budget between 1 and 100000),
  enabled boolean not null default true,
  calls_this_month integer not null default 0 check (calls_this_month >= 0),
  budget_month date not null default date_trunc('month', now())::date,
  created_by uuid not null references public.profiles (id),
  created_at timestamptz not null default now(),
  last_run_at timestamptz,
  last_error text
);
alter table public.connected_models enable row level security;
revoke all on public.connected_models from anon, authenticated;
grant select on public.connected_models to authenticated;
create policy "connected_models_select_member" on public.connected_models
  for select using (private.is_project_member(project_id, 'viewer'));

create table public.connected_probes (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects (id) on delete cascade,
  position integer not null check (position between 1 and 5),
  prompt text not null check (char_length(prompt) between 1 and 500),
  expected text not null check (char_length(expected) between 1 and 200),
  match_type text not null check (match_type in ('contains', 'exact')),
  unique (project_id, position)
);
alter table public.connected_probes enable row level security;
revoke all on public.connected_probes from anon, authenticated;
grant select on public.connected_probes to authenticated;
create policy "connected_probes_select_member" on public.connected_probes
  for select using (private.is_project_member(project_id, 'viewer'));

-- -- what nobody but the definer functions can touch --------------------------------------------------------------------
create table private.connected_secrets (
  model_id uuid primary key references public.connected_models (id) on delete cascade,
  key_id integer not null check (key_id between 1 and 1000),
  ephemeral_public bytea not null check (length(ephemeral_public) = 32),
  nonce bytea not null check (length(nonce) = 12),
  ciphertext bytea not null check (length(ciphertext) between 17 and 600)
);
create table private.connected_jobs (
  model_id uuid primary key references public.connected_models (id) on delete cascade,
  due_at timestamptz not null default now(),
  lease_until timestamptz,
  lease_token uuid,
  attempts integer not null default 0,
  state text not null default 'idle' check (state in ('idle', 'leased', 'dead'))
);
create index connected_jobs_due_idx on private.connected_jobs (due_at) where state <> 'dead';
create table private.probe_vectors (
  model_id uuid primary key references public.connected_models (id) on delete cascade,
  baseline bytea,  -- float32 rows, numbers only; no probe answer text is ever stored
  recent bytea,
  runs integer not null default 0
);
create table private.runner_audit (
  id bigint generated always as identity primary key,
  model_id uuid,  -- no foreign key: the trail outlives a deleted model (90-day retention)
  action text not null check (action in ('decrypt', 'claim', 'dead')),
  at timestamptz not null default now()
);
create index runner_audit_at_idx on private.runner_audit (at);
revoke all on private.runner_policy, private.connected_secrets, private.connected_jobs, private.probe_vectors,
  private.runner_audit from public, anon, authenticated;

-- -- helpers ---------------------------------------------------------------------------------------------------------
create function private.require_runner(p_secret text)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_hash bytea;
begin
  select runner_secret_hash into v_hash from private.runner_policy;
  if v_hash is null or p_secret is null or extensions.digest(p_secret, 'sha256') <> v_hash then
    raise exception 'unauthorized' using errcode = 'PT401';
  end if;
end;
$$;
revoke all on function private.require_runner(text) from public, anon, authenticated;

create function private.require_project_admin(p_project_id uuid)
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
  if (select auth.uid()) is null then
    raise exception 'authentication required' using errcode = 'PT401';
  end if;
  if not exists (select 1 from auth.users where id = (select auth.uid()) and email_confirmed_at is not null) then
    raise exception 'verify your email first' using errcode = 'PT403';
  end if;
  if not private.is_project_member(p_project_id, 'admin') then
    raise exception 'forbidden' using errcode = 'PT403';
  end if;
end;
$$;
revoke all on function private.require_project_admin(uuid) from public, anon, authenticated;

-- A lease check shared by the runner functions: the caller must hold the job's current, unexpired lease.
create function private.require_lease(p_model_id uuid, p_lease uuid)
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
  if p_lease is null or not exists (
    select 1 from private.connected_jobs
    where model_id = p_model_id and lease_token = p_lease and state = 'leased' and lease_until > now()
  ) then
    raise exception 'no lease' using errcode = 'PT409';
  end if;
end;
$$;
revoke all on function private.require_lease(uuid, uuid) from public, anon, authenticated;

-- -- what the website calls (with the user's session) ---------------------------------------------------------------
create function public.connect_model(
  p_project_id uuid, p_model_id uuid, p_provider text, p_model text, p_last4 text,
  p_key_id integer, p_ephemeral text, p_nonce text, p_ciphertext text,
  p_interval_minutes integer default 60, p_monthly_budget integer default 2000
)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_org uuid;
begin
  perform private.require_project_admin(p_project_id);
  if not (select enabled from private.runner_policy) then
    raise exception 'cloud connect is not available' using errcode = 'PT503';
  end if;
  if p_model_id is null then
    raise exception 'model id required' using errcode = 'PT422';
  end if;
  begin
    -- one model per project: connecting again replaces it (a new id, so the old ciphertext is gone with its row)
    delete from public.connected_models where project_id = p_project_id;
    insert into public.connected_models (id, project_id, provider, model, last4, interval_minutes, monthly_budget, created_by)
      values (p_model_id, p_project_id, p_provider, p_model, p_last4, p_interval_minutes, p_monthly_budget, (select auth.uid()));
    insert into private.connected_secrets (model_id, key_id, ephemeral_public, nonce, ciphertext)
      values (p_model_id, p_key_id, decode(p_ephemeral, 'base64'), decode(p_nonce, 'base64'), decode(p_ciphertext, 'base64'));
    insert into private.connected_jobs (model_id) values (p_model_id);
  exception
    when check_violation or invalid_parameter_value or not_null_violation or unique_violation then
      raise exception 'invalid connection settings' using errcode = 'PT422';
  end;
  select organization_id into v_org from public.projects where id = p_project_id;
  perform private.write_audit((select auth.uid()), v_org, 'connected_model.create', p_project_id::text, 'ok');
end;
$$;
revoke all on function public.connect_model(uuid, uuid, text, text, text, integer, text, text, text, integer, integer) from public, anon;
grant execute on function public.connect_model(uuid, uuid, text, text, text, integer, text, text, text, integer, integer) to authenticated;

create function public.update_connected_model(p_project_id uuid, p_interval_minutes integer, p_monthly_budget integer, p_enabled boolean)
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
  perform private.require_project_admin(p_project_id);
  begin
    update public.connected_models
      set interval_minutes = p_interval_minutes, monthly_budget = p_monthly_budget, enabled = p_enabled
      where project_id = p_project_id;
  exception when check_violation or not_null_violation then
    raise exception 'invalid settings' using errcode = 'PT422';
  end;
  -- re-enabling a dead job gives it a fresh start
  update private.connected_jobs j set state = 'idle', attempts = 0, due_at = now(), lease_until = null, lease_token = null
    from public.connected_models m where m.id = j.model_id and m.project_id = p_project_id and p_enabled and j.state = 'dead';
end;
$$;
revoke all on function public.update_connected_model(uuid, integer, integer, boolean) from public, anon;
grant execute on function public.update_connected_model(uuid, integer, integer, boolean) to authenticated;

create function public.delete_connected_model(p_project_id uuid)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_org uuid;
begin
  perform private.require_project_admin(p_project_id);
  delete from public.connected_models where project_id = p_project_id;  -- cascades: secret, job, vectors
  select organization_id into v_org from public.projects where id = p_project_id;
  perform private.write_audit((select auth.uid()), v_org, 'connected_model.delete', p_project_id::text, 'ok');
end;
$$;
revoke all on function public.delete_connected_model(uuid) from public, anon;
grant execute on function public.delete_connected_model(uuid) to authenticated;

-- p_probes: [{"prompt": "...", "expected": "...", "match_type": "contains"|"exact"}, ...] (1 to 5)
create function public.set_probes(p_project_id uuid, p_probes jsonb)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_item jsonb;
  v_pos integer := 0;
begin
  perform private.require_project_admin(p_project_id);
  if p_probes is null or jsonb_typeof(p_probes) <> 'array' or jsonb_array_length(p_probes) not between 1 and 5 then
    raise exception 'between 1 and 5 probes' using errcode = 'PT422';
  end if;
  delete from public.connected_probes where project_id = p_project_id;
  begin
    for v_item in select * from jsonb_array_elements(p_probes) loop
      v_pos := v_pos + 1;
      if jsonb_typeof(v_item) <> 'object' then
        raise exception 'bad probe' using errcode = 'PT422';
      end if;
      insert into public.connected_probes (project_id, position, prompt, expected, match_type)
        values (p_project_id, v_pos, v_item ->> 'prompt', v_item ->> 'expected', coalesce(v_item ->> 'match_type', 'contains'));
    end loop;
  exception when check_violation or not_null_violation then
    raise exception 'invalid probe' using errcode = 'PT422';
  end;
  -- new questions need a new baseline
  update private.probe_vectors v set baseline = null, recent = null, runs = 0
    from public.connected_models m where m.id = v.model_id and m.project_id = p_project_id;
end;
$$;
revoke all on function public.set_probes(uuid, jsonb) from public, anon;
grant execute on function public.set_probes(uuid, jsonb) to authenticated;

-- -- what the runner calls (public key + runner secret) ----------------------------------------------------------------
create function public.runner_claim_jobs(p_secret text)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_policy private.runner_policy;
  v_out jsonb := '[]'::jsonb;
  r record;
  v_token uuid;
  v_calls integer;
  v_probes jsonb;
begin
  perform private.require_runner(p_secret);
  select * into v_policy from private.runner_policy;
  if not v_policy.enabled then
    return v_out;
  end if;
  -- a new month resets every budget counter
  update public.connected_models set calls_this_month = 0, budget_month = date_trunc('month', now())::date
    where budget_month < date_trunc('month', now())::date;
  -- a lease that expired twice is a dead letter
  with dead as (
    update private.connected_jobs set state = 'dead', lease_until = null, lease_token = null
    where state = 'leased' and lease_until <= now() and attempts >= 2 returning model_id
  ), named as (
    update public.connected_models m set last_error = 'The runner could not finish two runs in a row. Save the settings again to retry.'
    from dead where m.id = dead.model_id returning m.id
  )
  insert into private.runner_audit (model_id, action) select id, 'dead' from named;

  for r in
    select j.model_id, m.project_id, m.provider, m.model, m.monthly_budget, m.calls_this_month
    from private.connected_jobs j join public.connected_models m on m.id = j.model_id
    where m.enabled and j.state <> 'dead' and j.due_at <= now()
      and (j.state = 'idle' or j.lease_until <= now())
    order by j.due_at
    limit v_policy.max_models_per_pass
    for update of j skip locked
  loop
    select count(*) + 2 into v_calls from public.connected_probes where project_id = r.project_id;  -- +2: two extra samples for self-consistency
    v_calls := least(v_calls, v_policy.max_calls_per_run);
    if v_calls <= 2 then
      continue;  -- no probes yet: nothing to ask
    end if;
    if r.calls_this_month + v_calls > r.monthly_budget then
      update public.connected_models set last_error = 'The monthly call budget is used up. Raise it or wait for next month.' where id = r.model_id;
      update private.connected_jobs set due_at = date_trunc('month', now()) + interval '1 month' where model_id = r.model_id;
      continue;
    end if;
    v_token := gen_random_uuid();
    update private.connected_jobs
      set state = 'leased', lease_token = v_token, lease_until = now() + make_interval(mins => v_policy.lease_minutes),
          attempts = attempts + 1
      where model_id = r.model_id;
    select coalesce(jsonb_agg(jsonb_build_object('position', position, 'prompt', prompt, 'expected', expected, 'match_type', match_type) order by position), '[]'::jsonb)
      into v_probes from public.connected_probes where project_id = r.project_id;
    insert into private.runner_audit (model_id, action) values (r.model_id, 'claim');
    v_out := v_out || jsonb_build_object('model_id', r.model_id, 'provider', r.provider, 'model', r.model, 'lease', v_token,
                                         'max_calls', v_calls, 'probes', v_probes);
  end loop;
  return v_out;
end;
$$;
revoke all on function public.runner_claim_jobs(text) from public;
grant execute on function public.runner_claim_jobs(text) to anon;

create function public.runner_get_secret(p_secret text, p_model_id uuid, p_lease uuid)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  s private.connected_secrets;
begin
  perform private.require_runner(p_secret);
  perform private.require_lease(p_model_id, p_lease);
  select * into s from private.connected_secrets where model_id = p_model_id;
  if not found then
    raise exception 'not found' using errcode = 'PT404';
  end if;
  insert into private.runner_audit (model_id, action) values (p_model_id, 'decrypt');
  return jsonb_build_object('key_id', s.key_id, 'ephemeral', encode(s.ephemeral_public, 'base64'),
                            'nonce', encode(s.nonce, 'base64'), 'ciphertext', encode(s.ciphertext, 'base64'));
end;
$$;
revoke all on function public.runner_get_secret(text, uuid, uuid) from public;
grant execute on function public.runner_get_secret(text, uuid, uuid) to anon;

create function public.runner_get_vectors(p_secret text, p_model_id uuid, p_lease uuid)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v private.probe_vectors;
begin
  perform private.require_runner(p_secret);
  perform private.require_lease(p_model_id, p_lease);
  select * into v from private.probe_vectors where model_id = p_model_id;
  return jsonb_build_object('baseline', encode(v.baseline, 'base64'), 'recent', encode(v.recent, 'base64'), 'runs', coalesce(v.runs, 0));
end;
$$;
revoke all on function public.runner_get_vectors(text, uuid, uuid) from public;
grant execute on function public.runner_get_vectors(text, uuid, uuid) to anon;

create function public.runner_save_vectors(p_secret text, p_model_id uuid, p_lease uuid, p_baseline text, p_recent text, p_runs integer)
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
  perform private.require_runner(p_secret);
  perform private.require_lease(p_model_id, p_lease);
  if coalesce(length(decode(p_baseline, 'base64')), 0) > 200000 or coalesce(length(decode(p_recent, 'base64')), 0) > 200000 then
    raise exception 'vectors too large' using errcode = 'PT422';
  end if;
  insert into private.probe_vectors (model_id, baseline, recent, runs)
    values (p_model_id, decode(p_baseline, 'base64'), decode(p_recent, 'base64'), p_runs)
    on conflict (model_id) do update set baseline = excluded.baseline, recent = excluded.recent, runs = excluded.runs;
end;
$$;
revoke all on function public.runner_save_vectors(text, uuid, uuid, text, text, integer) from public;
grant execute on function public.runner_save_vectors(text, uuid, uuid, text, text, integer) to anon;

-- p_events: [{"event_id": uuid, "signal": ..., "value": number, "occurred_at": iso, "meta": {...}}, ...] (at most 10)
create function public.runner_write_signals(p_secret text, p_model_id uuid, p_lease uuid, p_events jsonb)
returns integer
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_project uuid;
  v_event jsonb;
  v_value double precision;
  v_meta jsonb;
  v_occurred timestamptz;
  v_n integer := 0;
begin
  perform private.require_runner(p_secret);
  perform private.require_lease(p_model_id, p_lease);
  select project_id into v_project from public.connected_models where id = p_model_id;
  if p_events is null or jsonb_typeof(p_events) <> 'array' or jsonb_array_length(p_events) > 10 then
    raise exception 'invalid events' using errcode = 'PT422';
  end if;
  for v_event in select * from jsonb_array_elements(p_events) loop
    if (v_event ->> 'signal') not in ('embedding_drift', 'self_consistency', 'canary_accuracy', 'combined_score')
       or jsonb_typeof(v_event -> 'value') <> 'number' then
      raise exception 'invalid event' using errcode = 'PT422';
    end if;
    v_value := (v_event ->> 'value')::double precision;
    if v_value <> v_value or abs(v_value) >= 1e9 then
      raise exception 'invalid value' using errcode = 'PT422';
    end if;
    v_meta := coalesce(v_event -> 'meta', '{}'::jsonb);
    if jsonb_typeof(v_meta) <> 'object' or pg_column_size(v_meta) > 4096 or (select count(*) from jsonb_object_keys(v_meta)) > 32 then
      raise exception 'invalid meta' using errcode = 'PT422';
    end if;
    begin
      v_occurred := (v_event ->> 'occurred_at')::timestamptz;
    exception when others then
      raise exception 'invalid time' using errcode = 'PT422';
    end;
    if v_occurred > now() + interval '5 minutes' or v_occurred < now() - interval '1 day' then
      raise exception 'invalid time' using errcode = 'PT422';
    end if;
    insert into public.signal_records (project_id, event_id, signal, value, meta, occurred_at)
      values (v_project, (v_event ->> 'event_id')::uuid, v_event ->> 'signal', v_value,
              v_meta || jsonb_build_object('source', 'cloud_runner', 'mode', 'cloud_probe'), v_occurred)
      on conflict (project_id, event_id) do nothing;
    if found then
      v_n := v_n + 1;
    end if;
  end loop;
  return v_n;
end;
$$;
revoke all on function public.runner_write_signals(text, uuid, uuid, jsonb) from public;
grant execute on function public.runner_write_signals(text, uuid, uuid, jsonb) to anon;

-- p_outcome: 'ok' or one of the fixed failure codes. Only fixed sentences ever reach last_error (never provider text).
create function public.runner_finish_job(p_secret text, p_model_id uuid, p_lease uuid, p_outcome text, p_calls integer)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_job private.connected_jobs;
  v_interval integer;
  v_sentence text;
begin
  perform private.require_runner(p_secret);
  perform private.require_lease(p_model_id, p_lease);
  v_sentence := case p_outcome
    when 'ok' then null
    when 'provider_auth' then 'The provider rejected the key. Connect again with a new key.'
    when 'provider_error' then 'The provider did not answer. The runner will try again.'
    when 'bad_reply' then 'The model gave answers the runner could not use. The runner will try again.'
    when 'runner_error' then 'The runner had a problem. It will try again.'
    else null end;
  if p_outcome <> 'ok' and v_sentence is null then
    raise exception 'unknown outcome' using errcode = 'PT422';
  end if;
  select * into v_job from private.connected_jobs where model_id = p_model_id for update;
  select interval_minutes into v_interval from public.connected_models where id = p_model_id;
  update public.connected_models
    set calls_this_month = calls_this_month + greatest(0, least(coalesce(p_calls, 0), 50)),
        last_run_at = case when p_outcome = 'ok' then now() else last_run_at end,
        last_error = v_sentence
    where id = p_model_id;
  if p_outcome = 'ok' then
    update private.connected_jobs set state = 'idle', attempts = 0, lease_until = null, lease_token = null,
      due_at = now() + make_interval(mins => v_interval) where model_id = p_model_id;
  elsif p_outcome = 'provider_auth' or v_job.attempts >= 2 then
    -- a rejected key will not fix itself, and a second failure in a row stops the job until the user acts
    update private.connected_jobs set state = 'dead', lease_until = null, lease_token = null where model_id = p_model_id;
    insert into private.runner_audit (model_id, action) values (p_model_id, 'dead');
  else
    update private.connected_jobs set state = 'idle', lease_until = null, lease_token = null,
      due_at = now() + interval '5 minutes' where model_id = p_model_id;
  end if;
end;
$$;
revoke all on function public.runner_finish_job(text, uuid, uuid, text, integer) from public;
grant execute on function public.runner_finish_job(text, uuid, uuid, text, integer) to anon;

-- Aggregates only (no ids, no content), for the keep-alive alarm.
create function public.runner_health(p_secret text)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
begin
  perform private.require_runner(p_secret);
  return jsonb_build_object(
    'enabled', (select enabled from private.runner_policy),
    'models', (select count(*) from public.connected_models where enabled),
    'stale', (select count(*) from public.connected_models m join private.connected_jobs j on j.model_id = m.id
              where m.enabled and j.state <> 'dead' and j.due_at < now() - make_interval(mins => 2 * m.interval_minutes)),
    'dead', (select count(*) from private.connected_jobs where state = 'dead'),
    'decrypts_24h', (select count(*) from private.runner_audit where action = 'decrypt' and at > now() - interval '24 hours'),
    'claims_24h', (select count(*) from private.runner_audit where action = 'claim' and at > now() - interval '24 hours')
  );
end;
$$;
revoke all on function public.runner_health(text) from public;
grant execute on function public.runner_health(text) to anon;

-- Retention: the audit trail keeps 90 days.
select cron.schedule('driftwatch-runner-audit-prune', '17 4 * * *',
  $$delete from private.runner_audit where at < now() - interval '90 days'$$);

-- The export now includes the connected model's settings and probes (what the user chose), never any secret:
-- the secrets live in private tables that no client role can read, and RLS decides the rest (security invoker).
create or replace function public.export_my_data()
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
  select jsonb_build_object(
    'exported_at', now(),
    'profile', (select to_jsonb(p) from public.profiles p where p.id = (select auth.uid())),
    'organizations', coalesce((select jsonb_agg(to_jsonb(o)) from public.organizations o), '[]'::jsonb),
    'memberships', coalesce((select jsonb_agg(to_jsonb(m)) from public.organization_members m), '[]'::jsonb),
    'projects', coalesce((select jsonb_agg(to_jsonb(pr)) from public.projects pr), '[]'::jsonb),
    'api_keys', coalesce((
      select jsonb_agg(jsonb_build_object(
        'id', k.id, 'project_id', k.project_id, 'name', k.name, 'prefix', k.prefix,
        'created_at', k.created_at, 'last_used_at', k.last_used_at, 'revoked_at', k.revoked_at))
      from public.project_api_keys k), '[]'::jsonb),
    'connected_models', coalesce((select jsonb_agg(to_jsonb(c)) from public.connected_models c), '[]'::jsonb),
    'connected_probes', coalesce((select jsonb_agg(to_jsonb(cp)) from public.connected_probes cp), '[]'::jsonb),
    'signal_records_latest_10000', coalesce((
      select jsonb_agg(to_jsonb(r))
      from (select * from public.signal_records
            where project_id in (select id from public.projects)
            order by occurred_at desc limit 10000) r), '[]'::jsonb),
    'signal_hourly', coalesce((select jsonb_agg(to_jsonb(h)) from public.signal_hourly h), '[]'::jsonb),
    'audit_events', coalesce((select jsonb_agg(to_jsonb(a)) from public.audit_events a), '[]'::jsonb)
  );
$$;
revoke all on function public.export_my_data() from public, anon;
grant execute on function public.export_my_data() to authenticated;
