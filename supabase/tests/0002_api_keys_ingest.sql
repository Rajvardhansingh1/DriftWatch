-- PASS = a single row with result = 'PASS'. Any 'FAIL: ...' error is a bug.
begin;

insert into auth.users (id, email, email_confirmed_at, raw_user_meta_data) values
  ('11111111-1111-1111-1111-111111111111', 'a@test.local', now(), '{}'::jsonb),
  ('22222222-2222-2222-2222-222222222222', 'b@test.local', now(), '{}'::jsonb),
  ('33333333-3333-3333-3333-333333333333', 'u@test.local', null,  '{}'::jsonb);

set local role authenticated;
select set_config('request.jwt.claims',
  '{"sub":"11111111-1111-1111-1111-111111111111","role":"authenticated"}', true);
select set_config('test.org_a', (public.create_organization('Org A')).id::text, true);
insert into public.projects (organization_id, name)
  values (current_setting('test.org_a')::uuid, 'P-A');
select set_config('test.proj_a', (select id::text from public.projects limit 1), true);
select set_config('test.key_a',
  public.create_project_api_key(current_setting('test.proj_a')::uuid, 'laptop'), true);

-- Owner sees key metadata, never the hash; the audit row is visible to the org admin.
do $$ begin
  if (select count(*) from public.project_api_keys) <> 1 then
    raise exception 'FAIL: owner cannot list own key';
  end if;
  begin
    perform key_hash from public.project_api_keys;
    raise exception 'FAIL: key_hash readable';
  exception when insufficient_privilege then null; end;
  if (select count(*) from public.audit_events where action = 'api_key.create') <> 1 then
    raise exception 'FAIL: audit row missing or not visible to org admin';
  end if;
end $$;

-- User B cannot mint a key on A's project, nor see A's keys.
select set_config('request.jwt.claims',
  '{"sub":"22222222-2222-2222-2222-222222222222","role":"authenticated"}', true);
do $$ begin
  begin
    perform public.create_project_api_key(current_setting('test.proj_a')::uuid, 'evil');
    raise exception 'FAIL: B minted key on A project';
  exception when sqlstate 'PT403' then null; end;
  if (select count(*) from public.project_api_keys) <> 0 then
    raise exception 'FAIL: B sees A keys';
  end if;
end $$;

-- Unverified email cannot mint a key. Make the user an org admin first (as the
-- privileged role), so the email gate is the only thing that can reject the call.
reset role;
insert into public.organization_members (organization_id, user_id, role)
  values (current_setting('test.org_a')::uuid, '33333333-3333-3333-3333-333333333333', 'admin');
set local role authenticated;
select set_config('request.jwt.claims',
  '{"sub":"33333333-3333-3333-3333-333333333333","role":"authenticated"}', true);
do $$ begin
  begin
    perform public.create_project_api_key(current_setting('test.proj_a')::uuid, 'x');
    raise exception 'FAIL: unverified user minted key';
  exception when sqlstate 'PT403' then null; end;
end $$;

-- Ingest as anon with A's key.
set local role anon;
select set_config('request.jwt.claims', '{"role":"anon"}', true);
do $$
declare
  k text := current_setting('test.key_a');
  ev jsonb := jsonb_build_object(
    'schema_version', 1, 'event_id', '44444444-4444-4444-4444-444444444444',
    'occurred_at', to_char(now() at time zone 'utc', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
    'source', 'test', 'signal', 'combined_score', 'value', 0.1);
begin
  if public.ingest_event(k, ev) <> 'accepted' then raise exception 'FAIL: not accepted'; end if;
  if public.ingest_event(k, ev) <> 'duplicate' then raise exception 'FAIL: not duplicate'; end if;

  begin perform public.ingest_event('dw_0000000000_' || repeat('0', 64), ev);
        raise exception 'FAIL: bad key accepted';
  exception when sqlstate 'PT401' then null; end;

  begin perform public.ingest_event(substr(k, 1, 14) || repeat('0', 64), ev);
        raise exception 'FAIL: wrong secret accepted';
  exception when sqlstate 'PT401' then null; end;

  begin perform public.ingest_event(k, ev || '{"signal":"nope"}');
        raise exception 'FAIL: bad signal accepted';
  exception when sqlstate 'PT422' then null; end;

  begin perform public.ingest_event(k, ev || '{"extra":1}');
        raise exception 'FAIL: unknown field accepted';
  exception when sqlstate 'PT422' then null; end;

  begin perform public.ingest_event(k, ev || jsonb_build_object('event_id', gen_random_uuid(),
          'occurred_at', '2099-01-01T00:00:00Z'));
        raise exception 'FAIL: future timestamp accepted';
  exception when sqlstate 'PT422' then null; end;

  begin perform public.ingest_event(k, ev || '{"value":"1"}');
        raise exception 'FAIL: string value accepted';
  exception when sqlstate 'PT422' then null; end;

  begin perform public.ingest_event(k, ev || jsonb_build_object('event_id', gen_random_uuid(), 'value', 1e12));
        raise exception 'FAIL: huge value accepted';
  exception when sqlstate 'PT422' then null; end;

  -- anon has no table privileges at all.
  begin perform 1 from public.signal_records;
        raise exception 'FAIL: anon read signal_records';
  exception when insufficient_privilege then null; end;
end $$;

-- B cannot read A's signals.
set local role authenticated;
select set_config('request.jwt.claims',
  '{"sub":"22222222-2222-2222-2222-222222222222","role":"authenticated"}', true);
do $$ begin
  if (select count(*) from public.signal_records) <> 0 then
    raise exception 'FAIL: B reads A signals';
  end if;
end $$;

-- A revokes the key; it stops working.
select set_config('request.jwt.claims',
  '{"sub":"11111111-1111-1111-1111-111111111111","role":"authenticated"}', true);
select public.revoke_project_api_key((select id from public.project_api_keys limit 1));
set local role anon;
do $$ begin
  begin perform public.ingest_event(current_setting('test.key_a'), jsonb_build_object(
        'schema_version', 1, 'event_id', gen_random_uuid(),
        'occurred_at', to_char(now() at time zone 'utc', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
        'source', 'test', 'signal', 'combined_score', 'value', 0.1));
        raise exception 'FAIL: revoked key accepted';
  exception when sqlstate 'PT401' then null; end;
end $$;

select 'PASS' as result;
rollback;
