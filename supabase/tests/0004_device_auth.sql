-- PASS = one row, result = 'PASS'. Any 'FAIL: ...' is a bug. Leaves no data (rolled back).
-- Run in the Supabase SQL editor (runs as postgres).
begin;

insert into auth.users (id, email, email_confirmed_at, raw_user_meta_data) values
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'a@test.local', now(), '{}'::jsonb),
  ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 'b@test.local', now(), '{}'::jsonb),
  ('dddddddd-dddd-dddd-dddd-dddddddddddd', 'u@test.local', null, '{}'::jsonb);

set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa","role":"authenticated"}', true);
select set_config('test.pa', (public.create_project('Project A')).id::text, true);
select set_config('request.jwt.claims', '{"sub":"bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb","role":"authenticated"}', true);
select set_config('test.pb', (public.create_project('Project B')).id::text, true);

-- 1. anon starts a login: shape, alphabet, TTL; bad names are rejected.
set local role anon;
select set_config('request.jwt.claims', '{"role":"anon"}', true);
select set_config('test.start', public.start_device_login('laptop', 'Linux 6.1')::text, true);
do $$
declare s jsonb := current_setting('test.start')::jsonb;
begin
  if (s ->> 'device_code') !~ '^[0-9a-f]{64}$' then raise exception 'FAIL: device_code shape'; end if;
  if (s ->> 'user_code') !~ '^[BCDFGHJKLMNPQRSTVWXZ]{8}$' then raise exception 'FAIL: user_code shape'; end if;
  if (s ->> 'expires_in')::int <> 600 or (s ->> 'interval')::int <> 5 then raise exception 'FAIL: ttl/interval'; end if;
  begin perform public.start_device_login('   ', 'Linux'); raise exception 'FAIL: blank name accepted';
  exception when sqlstate 'PT422' then null; end;
  begin perform public.start_device_login(E'bad\nname', 'Linux'); raise exception 'FAIL: control char accepted';
  exception when sqlstate 'PT422' then null; end;
  begin perform public.start_device_login('x', repeat('o', 65)); raise exception 'FAIL: long os accepted';
  exception when sqlstate 'PT422' then null; end;
end $$;
select set_config('test.dc', current_setting('test.start')::jsonb ->> 'device_code', true);
select set_config('test.uc', current_setting('test.start')::jsonb ->> 'user_code', true);

-- 2. polling: pending, then slow_down; junk and unknown codes look identical.
do $$ begin
  if public.poll_device_login(current_setting('test.dc')) ->> 'status' <> 'authorization_pending' then
    raise exception 'FAIL: first poll should be pending'; end if;
  if public.poll_device_login(current_setting('test.dc')) ->> 'status' <> 'slow_down' then
    raise exception 'FAIL: fast second poll should be slow_down'; end if;
  if public.poll_device_login('nonsense') ->> 'status' <> 'expired_token' then raise exception 'FAIL: malformed'; end if;
  if public.poll_device_login(repeat('a', 64)) ->> 'status' <> 'expired_token' then raise exception 'FAIL: unknown'; end if;
  if public.poll_device_login(null) ->> 'status' <> 'expired_token' then raise exception 'FAIL: null'; end if;
end $$;

-- 3. anon cannot reach the approval functions; an unverified user is refused.
do $$ begin
  begin perform public.inspect_device_login('BBBBBBBB'); raise exception 'FAIL: anon inspect';
  exception when insufficient_privilege then null; end;
  begin perform public.approve_device_login('BBBBBBBB', current_setting('test.pa')::uuid); raise exception 'FAIL: anon approve';
  exception when insufficient_privilege then null; end;
  begin perform public.deny_device_login('BBBBBBBB'); raise exception 'FAIL: anon deny';
  exception when insufficient_privilege then null; end;
end $$;
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"dddddddd-dddd-dddd-dddd-dddddddddddd","role":"authenticated"}', true);
do $$ begin
  begin perform public.inspect_device_login(current_setting('test.uc')); raise exception 'FAIL: unverified inspect';
  exception when sqlstate 'PT403' then null; end;
end $$;

-- 4. Five wrong codes lock the user out, even for the right code.
select set_config('request.jwt.claims', '{"sub":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa","role":"authenticated"}', true);
do $$ begin
  for i in 1..5 loop
    if public.inspect_device_login('BBBBBBBB') ->> 'status' <> 'invalid' then raise exception 'FAIL: wrong code not invalid'; end if;
  end loop;
  begin perform public.inspect_device_login(current_setting('test.uc')); raise exception 'FAIL: lockout missing';
  exception when sqlstate 'PT429' then null; end;
end $$;
reset role;
delete from private.device_attempts;
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa","role":"authenticated"}', true);

-- 5. inspect (lower case, dashed), approve into a project A does not own, then into their own.
do $$
declare dashed text := lower(substr(current_setting('test.uc'), 1, 4) || '-' || substr(current_setting('test.uc'), 5));
        r jsonb;
begin
  r := public.inspect_device_login(dashed);
  if r ->> 'status' <> 'pending' or r ->> 'device_name' <> 'laptop' or r ->> 'device_os' <> 'Linux 6.1' then
    raise exception 'FAIL: inspect %', r; end if;
  begin perform public.approve_device_login(current_setting('test.uc'), current_setting('test.pb')::uuid);
        raise exception 'FAIL: approved into a foreign project';
  exception when sqlstate 'PT403' then null; end;
  if public.approve_device_login(current_setting('test.uc'), current_setting('test.pa')::uuid) ->> 'status' <> 'approved' then
    raise exception 'FAIL: approve'; end if;
  if public.approve_device_login(current_setting('test.uc'), current_setting('test.pa')::uuid) ->> 'status' <> 'invalid' then
    raise exception 'FAIL: second approve should be invalid'; end if;
end $$;

-- 6. The poll mints the key once; replay fails; the key really works.
set local role anon;
select set_config('request.jwt.claims', '{"role":"anon"}', true);
select set_config('test.poll', public.poll_device_login(current_setting('test.dc'))::text, true);
do $$
declare p jsonb := current_setting('test.poll')::jsonb;
begin
  if p ->> 'status' <> 'approved' then raise exception 'FAIL: poll after approve %', p; end if;
  if (p ->> 'api_key') !~ '^dw_[0-9a-f]{10}_[0-9a-f]{64}$' then raise exception 'FAIL: key shape'; end if;
  if (p ->> 'project_id') <> current_setting('test.pa') or p ->> 'project_name' <> 'Project A' then
    raise exception 'FAIL: project info'; end if;
  if public.poll_device_login(current_setting('test.dc')) ->> 'status' <> 'expired_token' then
    raise exception 'FAIL: replay accepted'; end if;
  if public.ingest_event(p ->> 'api_key', jsonb_build_object(
       'schema_version', 1, 'event_id', gen_random_uuid(),
       'occurred_at', to_char(now() at time zone 'utc', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
       'source', 'test', 'signal', 'combined_score', 'value', 0.1)) = 'duplicate' then
    raise exception 'FAIL: ingest with device key'; end if;
end $$;
reset role;
do $$ begin
  if (select count(*) from public.project_api_keys where project_id = current_setting('test.pa')::uuid
        and name = 'cli: laptop' and created_by = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa') <> 1 then
    raise exception 'FAIL: key row'; end if;
  if (select count(*) from public.audit_events where action = 'device.approve') <> 1
     or (select count(*) from public.audit_events where action = 'api_key.create_device') <> 1 then
    raise exception 'FAIL: audit rows'; end if;
end $$;

-- 7. Deny path.
set local role anon;
select set_config('request.jwt.claims', '{"role":"anon"}', true);
select set_config('test.start2', public.start_device_login('ci box', 'Linux')::text, true);
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa","role":"authenticated"}', true);
do $$ begin
  if public.deny_device_login(current_setting('test.start2')::jsonb ->> 'user_code') ->> 'status' <> 'denied' then
    raise exception 'FAIL: deny'; end if;
end $$;
set local role anon;
select set_config('request.jwt.claims', '{"role":"anon"}', true);
do $$ begin
  if public.poll_device_login(current_setting('test.start2')::jsonb ->> 'device_code') ->> 'status' <> 'access_denied' then
    raise exception 'FAIL: poll after deny'; end if;
end $$;

-- 8. Expired codes cannot be approved or polled.
select set_config('test.start3', public.start_device_login('old', 'Linux')::text, true);
reset role;
update private.device_codes set expires_at = now() - interval '1 minute'
  where user_code = current_setting('test.start3')::jsonb ->> 'user_code';
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa","role":"authenticated"}', true);
do $$ begin
  if public.approve_device_login(current_setting('test.start3')::jsonb ->> 'user_code',
                                 current_setting('test.pa')::uuid) ->> 'status' <> 'invalid' then
    raise exception 'FAIL: approved an expired code'; end if;
end $$;
set local role anon;
select set_config('request.jwt.claims', '{"role":"anon"}', true);
do $$ begin
  if public.poll_device_login(current_setting('test.start3')::jsonb ->> 'device_code') ->> 'status' <> 'expired_token' then
    raise exception 'FAIL: poll on expired'; end if;
end $$;

-- 9. The approver loses admin rights before the poll: no key is minted.
select set_config('test.start4', public.start_device_login('demoted', 'Linux')::text, true);
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa","role":"authenticated"}', true);
select public.approve_device_login(current_setting('test.start4')::jsonb ->> 'user_code', current_setting('test.pa')::uuid);
reset role;
update public.organization_members set role = 'viewer'
  where user_id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';
set local role anon;
select set_config('request.jwt.claims', '{"role":"anon"}', true);
do $$ begin
  if public.poll_device_login(current_setting('test.start4')::jsonb ->> 'device_code') ->> 'status' <> 'access_denied' then
    raise exception 'FAIL: demoted approver got a key'; end if;
end $$;
reset role;
do $$ begin
  if (select count(*) from public.project_api_keys where name = 'cli: demoted') <> 0 then
    raise exception 'FAIL: key minted for demoted approver'; end if;
end $$;
update public.organization_members set role = 'owner'
  where user_id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';

-- 10. Key limit: ten active keys already -> key_limit, nothing minted.
insert into public.project_api_keys (project_id, name, prefix, key_hash, created_by)
select current_setting('test.pa')::uuid, 'filler ' || g, 'dw_' || lpad(to_hex(g), 10, '0'),
       '\x00'::bytea, 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
from generate_series(1, 9) g;
set local role anon;
select set_config('request.jwt.claims', '{"role":"anon"}', true);
select set_config('test.start5', public.start_device_login('full', 'Linux')::text, true);
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa","role":"authenticated"}', true);
select public.approve_device_login(current_setting('test.start5')::jsonb ->> 'user_code', current_setting('test.pa')::uuid);
set local role anon;
select set_config('request.jwt.claims', '{"role":"anon"}', true);
do $$ begin
  if public.poll_device_login(current_setting('test.start5')::jsonb ->> 'device_code') ->> 'status' <> 'key_limit' then
    raise exception 'FAIL: key limit not enforced'; end if;
end $$;
reset role;
delete from public.project_api_keys where name like 'filler %';

-- 11. Self-revoke: the key stops working; repeats and garbage are silent no-ops.
set local role anon;
select set_config('request.jwt.claims', '{"role":"anon"}', true);
select public.revoke_api_key_by_secret(current_setting('test.poll')::jsonb ->> 'api_key');
select public.revoke_api_key_by_secret(current_setting('test.poll')::jsonb ->> 'api_key');
select public.revoke_api_key_by_secret('garbage');
select public.revoke_api_key_by_secret(null);
do $$ begin
  begin perform public.ingest_event(current_setting('test.poll')::jsonb ->> 'api_key', jsonb_build_object(
        'schema_version', 1, 'event_id', gen_random_uuid(),
        'occurred_at', to_char(now() at time zone 'utc', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
        'source', 'test', 'signal', 'combined_score', 'value', 0.1));
        raise exception 'FAIL: revoked key accepted';
  exception when sqlstate 'PT401' then null; end;
end $$;
reset role;
do $$ begin
  if (select revoked_at from public.project_api_keys where name = 'cli: laptop') is null then
    raise exception 'FAIL: key not revoked'; end if;
  if (select count(*) from public.audit_events where action = 'api_key.revoke_self') <> 1 then
    raise exception 'FAIL: self-revoke audit'; end if;
end $$;

-- 12. Device tables are invisible to clients.
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa","role":"authenticated"}', true);
do $$ begin
  begin perform 1 from private.device_codes; raise exception 'FAIL: authenticated can read device_codes';
  exception when insufficient_privilege then null; end;
end $$;
set local role anon;
select set_config('request.jwt.claims', '{"role":"anon"}', true);
do $$ begin
  begin perform 1 from private.device_codes; raise exception 'FAIL: anon can read device_codes';
  exception when insufficient_privilege then null; end;
end $$;

-- 13. Deleting the approver's account removes their device rows (through the real path).
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa","role":"authenticated"}', true);
select public.delete_my_account();
reset role;
do $$ begin
  if exists (select 1 from private.device_codes where approved_by = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa') then
    raise exception 'FAIL: device rows survived account delete'; end if;
  if not exists (select 1 from private.device_codes) then
    raise exception 'FAIL: expected unrelated device rows to remain'; end if;
end $$;

select 'PASS' as result;
rollback;
