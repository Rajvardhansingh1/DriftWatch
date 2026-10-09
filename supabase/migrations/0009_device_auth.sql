-- 0009: device-code login for the CLI (RFC 8628 shape).
-- The CLI has no session, so start/poll are callable by anon. They reveal nothing
-- without the 256-bit device code, which is stored only as a hash. The first poll
-- after approval mints a project API key and returns it once; the plaintext never
-- rests in the database.

create table private.device_codes (
  id uuid primary key default gen_random_uuid(),
  device_code_hash bytea not null unique,
  user_code text not null unique check (user_code ~ '^[BCDFGHJKLMNPQRSTVWXZ]{8}$'),
  device_name text not null check (char_length(device_name) between 1 and 64),
  device_os text not null check (char_length(device_os) between 1 and 64),
  created_at timestamptz not null default now(),
  expires_at timestamptz not null,
  last_polled_at timestamptz,
  approved_by uuid references auth.users (id) on delete cascade,
  project_id uuid references public.projects (id) on delete cascade,
  approved_at timestamptz,
  denied_at timestamptz,
  consumed_at timestamptz
);
create index device_codes_expires_idx on private.device_codes (expires_at);
create index device_codes_approved_by_idx on private.device_codes (approved_by);
create index device_codes_project_idx on private.device_codes (project_id);

create table private.device_attempts (
  user_id uuid not null references auth.users (id) on delete cascade,
  bucket timestamptz not null,
  n integer not null,
  primary key (user_id, bucket)
);
create table private.device_start_rate (
  bucket timestamptz primary key,
  n integer not null
);

alter table private.device_codes enable row level security;
alter table private.device_attempts enable row level security;
alter table private.device_start_rate enable row level security;
revoke all on private.device_codes, private.device_attempts, private.device_start_rate
  from public, anon, authenticated;

-- 20 consonants: no vowels (no words), no 0/O/1/I. 240 = 12 * 20, so rejecting
-- bytes >= 240 keeps every letter equally likely.
create function private.new_user_code()
returns text
language plpgsql
volatile
set search_path = ''
as $$
declare
  v_alpha constant text := 'BCDFGHJKLMNPQRSTVWXZ';
  v_out text := '';
  v_b integer;
begin
  while char_length(v_out) < 8 loop
    v_b := get_byte(extensions.gen_random_bytes(1), 0);
    if v_b < 240 then
      v_out := v_out || substr(v_alpha, (v_b % 20) + 1, 1);
    end if;
  end loop;
  return v_out;
end;
$$;
revoke all on function private.new_user_code() from public, anon, authenticated;

create function public.start_device_login(p_device_name text, p_device_os text)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_name text := btrim(coalesce(p_device_name, ''));
  v_os text := btrim(coalesce(p_device_os, ''));
  v_hits integer;
  v_secret text;
  v_code text;
begin
  if char_length(v_name) not between 1 and 64 or v_name ~ '[[:cntrl:]]'
     or char_length(v_os) not between 1 and 64 or v_os ~ '[[:cntrl:]]' then
    raise exception 'invalid device name' using errcode = 'PT422';
  end if;

  insert into private.device_start_rate (bucket, n) values (date_trunc('minute', now()), 1)
    on conflict (bucket) do update set n = private.device_start_rate.n + 1
    returning n into v_hits;
  if v_hits > 60 or (select count(*) from private.device_codes
                     where expires_at > now() and consumed_at is null) >= 500 then
    raise exception 'too many sign-in requests, try again in a minute' using errcode = 'PT429';
  end if;

  delete from private.device_codes where expires_at < now() - interval '1 day';
  delete from private.device_start_rate where bucket < now() - interval '1 hour';
  delete from private.device_attempts where bucket < now() - interval '1 hour';

  v_secret := encode(extensions.gen_random_bytes(32), 'hex');
  loop
    v_code := private.new_user_code();
    exit when not exists (select 1 from private.device_codes where user_code = v_code);
  end loop;

  insert into private.device_codes (device_code_hash, user_code, device_name, device_os, expires_at)
  values (extensions.digest(v_secret, 'sha256'), v_code, v_name, v_os, now() + interval '10 minutes');

  return jsonb_build_object('device_code', v_secret, 'user_code', v_code,
                            'expires_in', 600, 'interval', 5);
end;
$$;
revoke all on function public.start_device_login(text, text) from public;
grant execute on function public.start_device_login(text, text) to anon, authenticated;

create function public.poll_device_login(p_device_code text)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_row private.device_codes;
  v_org uuid;
  v_project_name text;
  v_prefix text;
  v_secret text;
begin
  if p_device_code is null or p_device_code !~ '^[0-9a-f]{64}$' then
    return jsonb_build_object('status', 'expired_token');
  end if;
  select * into v_row from private.device_codes
    where device_code_hash = extensions.digest(p_device_code, 'sha256')
    for update;
  if not found or v_row.consumed_at is not null or v_row.expires_at <= now() then
    return jsonb_build_object('status', 'expired_token');
  end if;
  if v_row.denied_at is not null then
    return jsonb_build_object('status', 'access_denied');
  end if;

  if v_row.approved_at is null then
    update private.device_codes set last_polled_at = now() where id = v_row.id;
    if v_row.last_polled_at is not null and v_row.last_polled_at > now() - interval '4 seconds' then
      return jsonb_build_object('status', 'slow_down');
    end if;
    return jsonb_build_object('status', 'authorization_pending');
  end if;

  -- Approved. The approver must still be an owner/admin of the project now.
  select p.organization_id, p.name into v_org, v_project_name
  from public.projects p
  where p.id = v_row.project_id
    and exists (select 1 from public.organization_members m
                where m.organization_id = p.organization_id
                  and m.user_id = v_row.approved_by
                  and m.status = 'active'
                  and m.role in ('owner', 'admin'));
  if v_org is null then
    update private.device_codes set consumed_at = now() where id = v_row.id;
    return jsonb_build_object('status', 'access_denied');
  end if;
  if (select count(*) from public.project_api_keys
      where project_id = v_row.project_id and revoked_at is null) >= 10 then
    update private.device_codes set consumed_at = now() where id = v_row.id;
    return jsonb_build_object('status', 'key_limit');
  end if;

  v_prefix := 'dw_' || encode(extensions.gen_random_bytes(5), 'hex');
  v_secret := encode(extensions.gen_random_bytes(32), 'hex');
  insert into public.project_api_keys (project_id, name, prefix, key_hash, created_by)
  values (v_row.project_id, left('cli: ' || v_row.device_name, 64), v_prefix,
          extensions.digest(v_secret, 'sha256'), v_row.approved_by);
  update private.device_codes set consumed_at = now() where id = v_row.id;
  perform private.write_audit(v_row.approved_by, v_org, 'api_key.create_device', v_row.project_id::text, 'ok');

  return jsonb_build_object('status', 'approved', 'api_key', v_prefix || '_' || v_secret,
                            'project_id', v_row.project_id, 'project_name', v_project_name);
end;
$$;
revoke all on function public.poll_device_login(text) from public;
grant execute on function public.poll_device_login(text) to anon, authenticated;

-- Shared by inspect/approve/deny. Returns a null row for a wrong code AFTER
-- recording the attempt; it must not raise there (a raise rolls back the counter).
create function private.find_device_code(p_user_code text)
returns private.device_codes
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_uid uuid := (select auth.uid());
  v_code text := upper(regexp_replace(coalesce(p_user_code, ''), '[[:space:]-]', '', 'g'));
  v_fails integer;
  v_row private.device_codes;
begin
  if v_uid is null then
    raise exception 'authentication required' using errcode = 'PT401';
  end if;
  if not exists (select 1 from auth.users where id = v_uid and email_confirmed_at is not null) then
    raise exception 'verify your email first' using errcode = 'PT403';
  end if;
  select coalesce(sum(n), 0) into v_fails from private.device_attempts
    where user_id = v_uid and bucket > now() - interval '15 minutes';
  if v_fails >= 5 then
    raise exception 'too many wrong codes, wait 15 minutes' using errcode = 'PT429';
  end if;

  select * into v_row from private.device_codes
    where user_code = v_code and expires_at > now()
      and approved_at is null and denied_at is null and consumed_at is null
    for update;
  if not found then
    insert into private.device_attempts (user_id, bucket, n)
      values (v_uid, date_trunc('minute', now()), 1)
      on conflict (user_id, bucket) do update set n = private.device_attempts.n + 1;
    return null;
  end if;
  return v_row;
end;
$$;
revoke all on function private.find_device_code(text) from public, anon, authenticated;

create function public.inspect_device_login(p_user_code text)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_row private.device_codes := private.find_device_code(p_user_code);
begin
  if v_row.id is null then
    return jsonb_build_object('status', 'invalid');
  end if;
  return jsonb_build_object('status', 'pending', 'device_name', v_row.device_name,
                            'device_os', v_row.device_os, 'requested_at', v_row.created_at,
                            'expires_at', v_row.expires_at);
end;
$$;
revoke all on function public.inspect_device_login(text) from public, anon;
grant execute on function public.inspect_device_login(text) to authenticated;

create function public.approve_device_login(p_user_code text, p_project_id uuid)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_row private.device_codes := private.find_device_code(p_user_code);
  v_org uuid;
begin
  if v_row.id is null then
    return jsonb_build_object('status', 'invalid');
  end if;
  if p_project_id is null or not private.is_project_member(p_project_id, 'admin') then
    raise exception 'forbidden' using errcode = 'PT403';
  end if;
  select organization_id into v_org from public.projects where id = p_project_id;
  update private.device_codes
    set approved_by = (select auth.uid()), project_id = p_project_id, approved_at = now(),
        expires_at = greatest(expires_at, now() + interval '2 minutes')
    where id = v_row.id;
  perform private.write_audit((select auth.uid()), v_org, 'device.approve', p_project_id::text, 'ok');
  return jsonb_build_object('status', 'approved');
end;
$$;
revoke all on function public.approve_device_login(text, uuid) from public, anon;
grant execute on function public.approve_device_login(text, uuid) to authenticated;

create function public.deny_device_login(p_user_code text)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_row private.device_codes := private.find_device_code(p_user_code);
begin
  if v_row.id is null then
    return jsonb_build_object('status', 'invalid');
  end if;
  update private.device_codes set denied_at = now() where id = v_row.id;
  perform private.write_audit((select auth.uid()), null, 'device.deny', v_row.id::text, 'ok');
  return jsonb_build_object('status', 'denied');
end;
$$;
revoke all on function public.deny_device_login(text) from public, anon;
grant execute on function public.deny_device_login(text) to authenticated;

-- Proof of possession revokes that one key. Always returns nothing (not an oracle).
create function public.revoke_api_key_by_secret(p_api_key text)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_key public.project_api_keys;
  v_org uuid;
begin
  if p_api_key is null or p_api_key !~ '^dw_[0-9a-f]{10}_[0-9a-f]{64}$' then
    return;
  end if;
  select * into v_key from public.project_api_keys
    where prefix = substr(p_api_key, 1, 13) and revoked_at is null
    for update;
  if not found or v_key.key_hash <> extensions.digest(substr(p_api_key, 15), 'sha256') then
    return;
  end if;
  update public.project_api_keys set revoked_at = now() where id = v_key.id;
  select organization_id into v_org from public.projects where id = v_key.project_id;
  perform private.write_audit(null, v_org, 'api_key.revoke_self', v_key.id::text, 'ok');
end;
$$;
revoke all on function public.revoke_api_key_by_secret(text) from public;
grant execute on function public.revoke_api_key_by_secret(text) to anon, authenticated;

create function private.prune_device_codes()
returns void
language sql
set search_path = ''
as $$
  delete from private.device_codes where expires_at < now() - interval '1 day';
  delete from private.device_start_rate where bucket < now() - interval '1 hour';
  delete from private.device_attempts where bucket < now() - interval '1 hour';
$$;
revoke all on function private.prune_device_codes() from public, anon, authenticated;
select cron.schedule('driftwatch-device-prune', '41 * * * *', 'select private.prune_device_codes()');
