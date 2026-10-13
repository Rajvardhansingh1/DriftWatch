-- 0010: the free allowance. Exact, atomic accounting for LLM calls the relay makes on a user's behalf.
--
-- The relay (Render) holds no Supabase service key. It calls reserve_quota / settle_quota with the public key,
-- authenticating with the project's own API key, exactly as the agent does for ingest_event.
--   reserve_quota  one unit, before the provider call. Atomic: a conditional upsert per counter, so 100
--                  concurrent callers can never push a counter past its cap. The ledger row has a unique
--                  idempotency key, so a retried request never counts twice.
--   settle_quota   after the call: 'ok' keeps the unit, 'failed' refunds it (user and global counters).
-- A reservation never settled (a relay crash) is refunded by the next reserve of the same user after 15 minutes.
-- Only the relay may meter: both functions need the relay secret (its hash is in quota_policies; unset = closed). Without
-- that, anyone holding a project key could call settle_quota('failed') between the relay's reserve and settle and get a
-- graded call refunded for free.
-- Limits live in a table row, changeable without a deploy. enabled = false is the database-side kill switch.
-- Lock order: usage_ledger (insert), usage_totals, usage_daily. Fixed, so concurrent calls queue, never deadlock.

create table private.quota_policies (
  name text primary key,
  per_user_cap integer not null check (per_user_cap >= 0),
  global_daily_cap integer not null check (global_daily_cap >= 0),
  enabled boolean not null default true,
  relay_secret_hash bytea  -- sha256 of the relay's secret; null until the owner sets it, and then the functions refuse
);
insert into private.quota_policies (name, per_user_cap, global_daily_cap) values ('free', 50, 500);

create table private.usage_totals (
  user_id uuid primary key,
  used integer not null default 0 check (used >= 0)
);
create table private.usage_daily (
  day date primary key,
  used integer not null default 0 check (used >= 0)
);
create table private.usage_ledger (
  id bigint generated always as identity primary key,
  user_id uuid not null,
  project_id uuid not null,
  idempotency_key uuid not null,
  state text not null default 'reserved' check (state in ('reserved', 'settled', 'refunded')),
  day date not null default current_date,
  created_at timestamptz not null default now(),
  unique (user_id, idempotency_key)
);
create index usage_ledger_stale_idx on private.usage_ledger (user_id, created_at) where state = 'reserved';
revoke all on private.quota_policies, private.usage_totals, private.usage_daily, private.usage_ledger
  from public, anon, authenticated;

create function private.require_relay(p_secret text)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_hash bytea;
begin
  select relay_secret_hash into v_hash from private.quota_policies where name = 'free';
  if v_hash is null or p_secret is null or extensions.digest(p_secret, 'sha256') <> v_hash then
    raise exception 'unauthorized' using errcode = 'PT401';
  end if;
end;
$$;
revoke all on function private.require_relay(text) from public, anon, authenticated;

-- Resolves an API key to its owner, or fails the same way for malformed, unknown and revoked keys.
create function private.quota_key_owner(p_api_key text)
returns table (user_id uuid, project_id uuid)
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_key public.project_api_keys;
begin
  if p_api_key is null or p_api_key !~ '^dw_[0-9a-f]{10}_[0-9a-f]{64}$' then
    raise exception 'unauthorized' using errcode = 'PT401';
  end if;
  select * into v_key from public.project_api_keys
    where prefix = substr(p_api_key, 1, 13) and revoked_at is null;
  if not found or v_key.key_hash <> extensions.digest(substr(p_api_key, 15), 'sha256') then
    raise exception 'unauthorized' using errcode = 'PT401';
  end if;
  user_id := v_key.created_by;
  project_id := v_key.project_id;
  return next;
end;
$$;
revoke all on function private.quota_key_owner(text) from public, anon, authenticated;

create function public.reserve_quota(p_api_key text, p_idempotency_key uuid, p_relay_secret text)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_user uuid;
  v_project uuid;
  v_policy private.quota_policies;
  v_ledger_id bigint;
  v_used integer;
  v_day_used integer;
begin
  perform private.require_relay(p_relay_secret);
  select o.user_id, o.project_id into v_user, v_project from private.quota_key_owner(p_api_key) o;
  if p_idempotency_key is null then
    raise exception 'idempotency key required' using errcode = 'PT422';
  end if;
  if not exists (select 1 from auth.users where id = v_user and email_confirmed_at is not null) then
    raise exception 'verify your email first' using errcode = 'PT403';
  end if;
  select * into v_policy from private.quota_policies where name = 'free';
  if not found or not v_policy.enabled then
    raise exception 'free allowance is switched off' using errcode = 'PT503';
  end if;

  -- Self-heal: a reservation nobody settled for 15 minutes is refunded (a relay crash must not eat the allowance).
  with stale as (
    update private.usage_ledger set state = 'refunded'
    where user_id = v_user and state = 'reserved' and created_at < now() - interval '15 minutes'
    returning day
  ), per_day as (
    select day, count(*)::int as n from stale group by day
  ), d as (
    update private.usage_daily u set used = greatest(u.used - p.n, 0) from per_day p where u.day = p.day returning 1
  )
  update private.usage_totals t set used = greatest(t.used - (select count(*) from stale), 0)
  where t.user_id = v_user and exists (select 1 from stale);

  -- Idempotency first: a replay returns the earlier result and counts nothing.
  insert into private.usage_ledger (user_id, project_id, idempotency_key)
    values (v_user, v_project, p_idempotency_key)
    on conflict (user_id, idempotency_key) do nothing
    returning id into v_ledger_id;
  if v_ledger_id is null then
    select used into v_used from private.usage_totals where user_id = v_user;
    return jsonb_build_object('replay', true, 'used', coalesce(v_used, 0), 'cap', v_policy.per_user_cap,
                              'remaining', greatest(v_policy.per_user_cap - coalesce(v_used, 0), 0));
  end if;

  -- Each counter is one conditional upsert: the cap check and the increment cannot be separated by another caller.
  insert into private.usage_totals as t (user_id, used) values (v_user, 1)
    on conflict (user_id) do update set used = t.used + 1 where t.used < v_policy.per_user_cap
    returning t.used into v_used;
  if v_used is null then
    raise exception 'free allowance used' using errcode = 'PT429';  -- rolls back the ledger row too
  end if;
  insert into private.usage_daily as d (day, used) values (current_date, 1)
    on conflict (day) do update set used = d.used + 1 where d.used < v_policy.global_daily_cap
    returning d.used into v_day_used;
  if v_day_used is null then
    raise exception 'daily free budget reached' using errcode = 'PT503';  -- rolls back the user counter too
  end if;

  return jsonb_build_object('replay', false, 'used', v_used, 'cap', v_policy.per_user_cap,
                            'remaining', v_policy.per_user_cap - v_used);
end;
$$;
revoke all on function public.reserve_quota(text, uuid, text) from public;
grant execute on function public.reserve_quota(text, uuid, text) to anon, authenticated;

create function public.settle_quota(p_api_key text, p_idempotency_key uuid, p_outcome text, p_relay_secret text)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_user uuid;
  v_row private.usage_ledger;
  v_used integer;
  v_cap integer;
begin
  perform private.require_relay(p_relay_secret);
  select o.user_id into v_user from private.quota_key_owner(p_api_key) o;
  if p_outcome is null or p_outcome not in ('ok', 'failed') then
    raise exception 'outcome must be ok or failed' using errcode = 'PT422';
  end if;
  -- The row lock makes a double settle (or a settle racing the self-heal) a no-op for the second caller.
  select * into v_row from private.usage_ledger
    where user_id = v_user and idempotency_key = p_idempotency_key for update;
  if found and v_row.state = 'reserved' then
    if p_outcome = 'ok' then
      update private.usage_ledger set state = 'settled' where id = v_row.id;
    else
      update private.usage_ledger set state = 'refunded' where id = v_row.id;
      update private.usage_totals set used = greatest(used - 1, 0) where user_id = v_user;
      update private.usage_daily set used = greatest(used - 1, 0) where day = v_row.day;
    end if;
  end if;
  select used into v_used from private.usage_totals where user_id = v_user;
  select per_user_cap into v_cap from private.quota_policies where name = 'free';
  return jsonb_build_object('used', coalesce(v_used, 0), 'cap', coalesce(v_cap, 0),
                            'remaining', greatest(coalesce(v_cap, 0) - coalesce(v_used, 0), 0));
end;
$$;
revoke all on function public.settle_quota(text, uuid, text, text) from public;
grant execute on function public.settle_quota(text, uuid, text, text) to anon, authenticated;

-- For the console: "free allowance: N of 50 used". Own numbers only.
create function public.my_quota()
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  v_used integer;
  v_cap integer;
  v_enabled boolean;
begin
  if (select auth.uid()) is null then
    raise exception 'authentication required' using errcode = 'PT401';
  end if;
  select used into v_used from private.usage_totals where user_id = (select auth.uid());
  select per_user_cap, enabled into v_cap, v_enabled from private.quota_policies where name = 'free';
  return jsonb_build_object('used', coalesce(v_used, 0), 'cap', coalesce(v_cap, 0), 'enabled', coalesce(v_enabled, false));
end;
$$;
revoke all on function public.my_quota() from public, anon;
grant execute on function public.my_quota() to authenticated;
