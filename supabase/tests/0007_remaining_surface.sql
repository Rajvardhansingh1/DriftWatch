-- PASS = a single row with result = 'PASS'. Any 'FAIL: ...' error is a bug. Leaves no data (rolled back).
-- Covers the public surface the other SQL tests do not touch: the hourly rollup table, create_organization and the
-- new-user trigger (handle_new_user). Launch gate J3: every public table and function is exercised by a SQL test.
begin;

-- handle_new_user: a new auth user gets a profile row, with nothing else granted.
insert into auth.users (id, email, email_confirmed_at, raw_user_meta_data) values
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'a@test.local', now(), '{}'::jsonb),
  ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 'b@test.local', now(), '{}'::jsonb);
do $$ begin
  if (select count(*) from public.profiles where id in ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb')) <> 2 then
    raise exception 'FAIL: handle_new_user did not create the profiles';
  end if;
  if exists (select 1 from public.organization_members where user_id in ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb')) then
    raise exception 'FAIL: a new user already belongs to an organization';
  end if;
end $$;

-- create_organization: anon is refused; a signed-in user becomes the owner; nobody else sees the organization.
set local role anon;
select set_config('request.jwt.claims', '{"role":"anon"}', true);
do $$ begin
  begin perform public.create_organization('Evil'); raise exception 'FAIL: anon created an organization';
  exception when insufficient_privilege then null; end;
end $$;
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa","role":"authenticated"}', true);
select set_config('test.org', (public.create_organization('A Org')).id::text, true);
do $$ begin
  if (select role from public.organization_members where organization_id = current_setting('test.org')::uuid and user_id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa') <> 'owner' then
    raise exception 'FAIL: the creator is not the owner';
  end if;
end $$;
select set_config('request.jwt.claims', '{"sub":"bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb","role":"authenticated"}', true);
do $$ begin
  if exists (select 1 from public.organizations where id = current_setting('test.org')::uuid) then
    raise exception 'FAIL: B can see A''s organization';
  end if;
end $$;

-- signal_hourly: members read their own project's rollup, never another's; no client can write it.
select set_config('request.jwt.claims', '{"sub":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa","role":"authenticated"}', true);
select set_config('test.pa', (public.create_project('Project A')).id::text, true);
select set_config('request.jwt.claims', '{"sub":"bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb","role":"authenticated"}', true);
select set_config('test.pb', (public.create_project('Project B')).id::text, true);
reset role;
insert into public.signal_hourly (project_id, signal, hour, n, avg_value, max_value) values
  (current_setting('test.pa')::uuid, 'embedding_drift', date_trunc('hour', now() - interval '3 hours'), 10, 0.2, 0.4),
  (current_setting('test.pb')::uuid, 'embedding_drift', date_trunc('hour', now() - interval '3 hours'), 10, 0.9, 0.9);
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa","role":"authenticated"}', true);
do $$ begin
  if (select count(*) from public.signal_hourly) <> 1 or (select avg_value from public.signal_hourly) <> 0.2 then
    raise exception 'FAIL: A should see exactly their own hourly row';
  end if;
  begin insert into public.signal_hourly (project_id, signal, hour, n, avg_value, max_value) values (current_setting('test.pa')::uuid, 'x', now(), 1, 0, 0);
    raise exception 'FAIL: a client inserted into signal_hourly';
  exception when insufficient_privilege then null; end;
  begin update public.signal_hourly set avg_value = 0; raise exception 'FAIL: a client updated signal_hourly';
  exception when insufficient_privilege then null; end;
  begin delete from public.signal_hourly; raise exception 'FAIL: a client deleted from signal_hourly';
  exception when insufficient_privilege then null; end;
end $$;
set local role anon;
select set_config('request.jwt.claims', '{"role":"anon"}', true);
do $$ begin
  begin perform * from public.signal_hourly; raise exception 'FAIL: anon reads signal_hourly';
  exception when insufficient_privilege then null; end;
end $$;

-- Least privilege (0013): the table privileges of anon and authenticated are exactly the expected ones. A table that
-- regains broad rights (a default grant, a forgotten revoke) fails here.
reset role;
do $$
declare
  r record;
  expected jsonb := '{
    "audit_events": ["SELECT"], "connected_models": ["SELECT"], "connected_probes": ["SELECT"], "signal_hourly": ["SELECT"],
    "organization_members": ["DELETE", "SELECT", "UPDATE"], "organizations": ["DELETE", "SELECT", "UPDATE"],
    "profiles": ["SELECT", "UPDATE"], "projects": ["DELETE", "SELECT"], "signal_records": ["DELETE", "SELECT"]
  }';
begin
  if exists (select 1 from information_schema.role_table_grants where table_schema = 'public' and grantee = 'anon') then
    raise exception 'FAIL: anon holds table privileges: %', (select string_agg(table_name || ':' || privilege_type, ', ') from information_schema.role_table_grants where table_schema = 'public' and grantee = 'anon');
  end if;
  for r in
    select table_name, array_agg(privilege_type order by privilege_type) as have
    from information_schema.role_table_grants
    where table_schema = 'public' and grantee = 'authenticated' and table_name <> 'project_api_keys'
    group by table_name
  loop
    if not expected ? r.table_name then
      raise exception 'FAIL: authenticated has unexpected privileges on %: %', r.table_name, r.have;
    end if;
    if to_jsonb(r.have) <> (expected -> r.table_name) then
      raise exception 'FAIL: authenticated privileges on % are % but should be %', r.table_name, r.have, expected -> r.table_name;
    end if;
  end loop;
end $$;

-- Direct inserts into signal_records are closed: ingest_event is the only way in (it enforces the limits).
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa","role":"authenticated"}', true);
do $$ begin
  begin insert into public.signal_records (project_id, event_id, signal, value, occurred_at) values (current_setting('test.pa')::uuid, gen_random_uuid(), 'embedding_drift', 0.1, now());
    raise exception 'FAIL: a member inserted into signal_records directly';
  exception when insufficient_privilege then null; end;
  begin update public.projects set organization_id = gen_random_uuid(); raise exception 'FAIL: a client moved a project to another organization';
  exception when insufficient_privilege then null; end;
  update public.projects set name = 'Renamed' where id = current_setting('test.pa')::uuid;  -- renaming still works
end $$;
reset role;

-- TRUNCATE is not subject to row-level security, so nobody who is not the owner may hold it.
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa","role":"authenticated"}', true);
do $$ begin
  begin truncate public.profiles; raise exception 'FAIL: authenticated can truncate profiles';
  exception when insufficient_privilege then null; end;
end $$;
set local role anon;
select set_config('request.jwt.claims', '{"role":"anon"}', true);
do $$ begin
  begin perform * from public.profiles; raise exception 'FAIL: anon reads profiles';
  exception when insufficient_privilege then null; end;
  begin perform * from public.organizations; raise exception 'FAIL: anon reads organizations';
  exception when insufficient_privilege then null; end;
  begin perform * from public.organization_members; raise exception 'FAIL: anon reads organization_members';
  exception when insufficient_privilege then null; end;
  begin truncate public.organizations; raise exception 'FAIL: anon can truncate organizations';
  exception when insufficient_privilege then null; end;
end $$;
reset role;

-- Deny by default: a table and a function created now get no rights for the API roles until they are granted.
create table public.zz_probe_table (id int);
create function public.zz_probe_fn() returns int language sql as 'select 1';
do $$ begin
  if has_table_privilege('anon', 'public.zz_probe_table', 'select') or has_table_privilege('authenticated', 'public.zz_probe_table', 'select') then
    raise exception 'FAIL: a new table is readable by the API roles by default';
  end if;
  if has_function_privilege('anon', 'public.zz_probe_fn()', 'execute') or has_function_privilege('authenticated', 'public.zz_probe_fn()', 'execute') then
    raise exception 'FAIL: a new function is executable by the API roles by default';
  end if;
end $$;

select 'PASS' as result;
rollback;
