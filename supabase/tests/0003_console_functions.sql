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

do $$ begin
  if (select count(*) from public.organizations) <> 1 then raise exception 'FAIL: expected exactly one personal org'; end if;
  if (select name from public.projects where id = current_setting('test.p1')::uuid) <> 'First' then
    raise exception 'FAIL: name not trimmed'; end if;
  begin perform public.create_project('   ');
        raise exception 'FAIL: blank name accepted';
  exception when sqlstate 'PT422' then null; end;
  perform public.create_project('P3'); perform public.create_project('P4'); perform public.create_project('P5');
  begin perform public.create_project('P6');
        raise exception 'FAIL: sixth project accepted';
  exception when sqlstate 'PT422' then null; end;
end $$;

-- A's export has A's data, key metadata, and no key_hash.
do $$
declare e jsonb := public.export_my_data();
begin
  if jsonb_array_length(e -> 'projects') <> 5 then raise exception 'FAIL: export projects'; end if;
  if jsonb_array_length(e -> 'api_keys') <> 1 then raise exception 'FAIL: export api_keys'; end if;
  if e::text like '%key_hash%' then raise exception 'FAIL: key_hash in export'; end if;
  if (e -> 'profile' ->> 'id') <> 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa' then raise exception 'FAIL: profile'; end if;
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
end $$;

-- A deletes the account: org, projects, keys and the user are gone; B untouched.
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa","role":"authenticated"}', true);
select public.delete_my_account();
reset role;
do $$ begin
  if exists (select 1 from auth.users where id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa') then raise exception 'FAIL: user remains'; end if;
  if exists (select 1 from public.profiles where id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa') then raise exception 'FAIL: profile remains'; end if;
  if (select count(*) from public.projects) <> 0 then raise exception 'FAIL: projects remain'; end if;
  if (select count(*) from public.project_api_keys) <> 0 then raise exception 'FAIL: keys remain'; end if;
  if not exists (select 1 from auth.users where id = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb') then raise exception 'FAIL: B deleted'; end if;
  if not exists (select 1 from public.audit_events where action = 'account.delete' and actor_user_id is null) then
    raise exception 'FAIL: anonymised audit row missing';
  end if;
end $$;

select 'PASS' as result;
rollback;
