-- PASS = one row, result = 'PASS'. Any 'FAIL: ...' is a bug.
begin;

insert into auth.users (id, email, email_confirmed_at, raw_user_meta_data) values
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'a@test.local', now(), '{}'::jsonb),
  ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 'b@test.local', now(), '{}'::jsonb);

set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa","role":"authenticated"}', true);

-- A creates projects (the personal org is created once and reused).
select set_config('test.p1', (public.create_project('  First   ')).id::text, true);
select set_config('test.p2', (public.create_project('Second')).id::text, true);
select set_config('test.key', public.create_project_api_key(current_setting('test.p1')::uuid, 'laptop'), true);
select set_config('test.org', (select id::text from public.organizations limit 1), true);

do $$ begin
  if (select count(*) from public.organizations) <> 1 then raise exception 'FAIL: expected exactly one personal org'; end if;
  if (select name from public.projects where id = current_setting('test.p1')::uuid) is distinct from 'First' then
    raise exception 'FAIL: name not trimmed'; end if;
  begin perform public.create_project('   ');
        raise exception 'FAIL: blank name accepted';
  exception when sqlstate 'PT422' then null; end;
  perform public.create_project('P3'); perform public.create_project('P4'); perform public.create_project('P5');
  begin perform public.create_project('P6');
        raise exception 'FAIL: sixth project accepted';
  exception when sqlstate 'PT422' then null; end;
end $$;

-- Leaving the personal org must not reset the limit (simulated as postgres: membership row removed).
reset role;
delete from public.organization_members
  where user_id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa' and organization_id = current_setting('test.org')::uuid;
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa","role":"authenticated"}', true);
do $$ begin
  begin perform public.create_project('bypass');
        raise exception 'FAIL: limit bypass via leaving org';
  exception when sqlstate 'PT422' then null; end;
end $$;
reset role;
insert into public.organization_members (organization_id, user_id, role)
  values (current_setting('test.org')::uuid, 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'owner');
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa","role":"authenticated"}', true);

-- Projects cannot be moved between orgs (no column privilege on organization_id).
do $$ begin
  begin update public.projects set organization_id = organization_id where id = current_setting('test.p1')::uuid;
        raise exception 'FAIL: organization_id update allowed';
  exception when insufficient_privilege then null; end;
end $$;

-- Direct inserts are closed: projects only come from create_project.
do $$ begin
  begin insert into public.projects (organization_id, name)
          values (current_setting('test.org')::uuid, 'sneaky');
        raise exception 'FAIL: direct project insert allowed';
  exception when insufficient_privilege then null; end;
end $$;

-- A's export has A's data, key metadata, and no key_hash.
do $$
declare e jsonb := public.export_my_data();
begin
  if jsonb_array_length(e -> 'projects') <> 5 then raise exception 'FAIL: export projects'; end if;
  if jsonb_array_length(e -> 'api_keys') <> 1 then raise exception 'FAIL: export api_keys'; end if;
  if e::text like '%key_hash%' then raise exception 'FAIL: key_hash in export'; end if;
  if (e -> 'profile' ->> 'id') is distinct from 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa' then raise exception 'FAIL: profile'; end if;
end $$;

-- B sees none of A's data.
select set_config('request.jwt.claims', '{"sub":"bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb","role":"authenticated"}', true);
do $$
declare e jsonb := public.export_my_data();
begin
  if jsonb_array_length(e -> 'projects') <> 0 or jsonb_array_length(e -> 'api_keys') <> 0
     or jsonb_array_length(e -> 'organizations') <> 0 then
    raise exception 'FAIL: B export leaks A data';
  end if;
end $$;

-- B creates a project of their own (used by the cross-org key case below).
select set_config('test.bp', (public.create_project('B project')).id::text, true);

-- anon cannot call any of the three.
set local role anon;
select set_config('request.jwt.claims', '{"role":"anon"}', true);
do $$ begin
  begin perform public.create_project('x'); raise exception 'FAIL: anon create_project';
  exception when insufficient_privilege then null; end;
  begin perform public.delete_my_account(); raise exception 'FAIL: anon delete';
  exception when insufficient_privilege then null; end;
  begin perform public.export_my_data(); raise exception 'FAIL: anon export';
  exception when insufficient_privilege then null; end;
  begin perform 1 from public.projects; raise exception 'FAIL: anon can select projects';
  exception when insufficient_privilege then null; end;
end $$;

-- Guard: C owns an org with another active member (B), so delete_my_account must refuse.
reset role;
insert into auth.users (id, email, email_confirmed_at, raw_user_meta_data) values
  ('cccccccc-cccc-cccc-cccc-cccccccccccc', 'c@test.local', now(), '{}'::jsonb);
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"cccccccc-cccc-cccc-cccc-cccccccccccc","role":"authenticated"}', true);
select public.create_project('C project');
reset role;
insert into public.organization_members (organization_id, user_id, role, status)
  select id, 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 'member', 'active'
  from public.organizations where created_by = 'cccccccc-cccc-cccc-cccc-cccccccccccc';
set local role authenticated;
do $$ begin
  begin perform public.delete_my_account();
        raise exception 'FAIL: guard did not block';
  exception when sqlstate 'PT422' then null; end;
end $$;
reset role;
delete from public.organization_members
  where user_id = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
    and organization_id in (select id from public.organizations where created_by = 'cccccccc-cccc-cccc-cccc-cccccccccccc');
do $$ begin
  if not exists (select 1 from auth.users where id = 'cccccccc-cccc-cccc-cccc-cccccccccccc') then
    raise exception 'FAIL: C deleted despite guard'; end if;
end $$;

-- Cross-org key: created by A inside B's project (no FK cascade from A's deletion).
insert into public.project_api_keys (project_id, name, prefix, key_hash, created_by)
values (current_setting('test.bp')::uuid, 'crossorg', 'dw_crossorg1', decode('00', 'hex'),
        'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa');

-- A deletes the account: org, projects, keys and the user are gone; B untouched.
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa","role":"authenticated"}', true);
select public.delete_my_account();
reset role;
do $$ begin
  if exists (select 1 from auth.users where id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa') then raise exception 'FAIL: user remains'; end if;
  if exists (select 1 from public.profiles where id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa') then raise exception 'FAIL: profile remains'; end if;
  if exists (select 1 from public.organizations where id = current_setting('test.org')::uuid) then raise exception 'FAIL: org remains'; end if;
  if exists (select 1 from public.projects
             where id in (current_setting('test.p1')::uuid, current_setting('test.p2')::uuid)) then
    raise exception 'FAIL: projects remain'; end if;
  if exists (select 1 from public.project_api_keys where prefix = left(current_setting('test.key'), 13)) then
    raise exception 'FAIL: keys remain'; end if;
  if exists (select 1 from public.project_api_keys where prefix = 'dw_crossorg1') then
    raise exception 'FAIL: cross-org key remains'; end if;
  if not exists (select 1 from public.projects where id = current_setting('test.bp')::uuid) then
    raise exception 'FAIL: B project deleted'; end if;
  if not exists (select 1 from auth.users where id = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb') then raise exception 'FAIL: B deleted'; end if;
  if not exists (select 1 from public.audit_events where action = 'account.delete' and actor_user_id is null
                 and occurred_at = now()) then
    raise exception 'FAIL: anonymised audit row missing';
  end if;
end $$;

select 'PASS' as result;
rollback;
