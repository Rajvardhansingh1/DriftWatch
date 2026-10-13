-- PASS = a single row with result = 'PASS'. Any 'FAIL: ...' error is a bug. Leaves no data (rolled back).
-- (The 100-concurrent-callers check cannot run inside one transaction: scripts/test_quota_concurrency_local.py does it.)
begin;

insert into auth.users (id, email, email_confirmed_at, raw_user_meta_data) values
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'a@test.local', now(), '{}'::jsonb),
  ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 'b@test.local', now(), '{}'::jsonb),
  ('dddddddd-dddd-dddd-dddd-dddddddddddd', 'u@test.local', null, '{}'::jsonb);


-- The relay's secret: tests call through helpers that add it, except where a test is about the secret itself.
update private.quota_policies set relay_secret_hash = extensions.digest('relay-secret', 'sha256') where name = 'free';
create function pg_temp.rq(k text, i uuid) returns jsonb language sql as $f$ select public.reserve_quota(k, i, 'relay-secret') $f$;
create function pg_temp.sq(k text, i uuid, o text) returns jsonb language sql as $f$ select public.settle_quota(k, i, o, 'relay-secret') $f$;
grant execute on function pg_temp.rq(text, uuid), pg_temp.sq(text, uuid, text) to anon, authenticated;

set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa","role":"authenticated"}', true);
select set_config('test.pa', (public.create_project('Project A')).id::text, true);
select set_config('test.key_a', public.create_project_api_key(current_setting('test.pa')::uuid, 'laptop'), true);
select set_config('test.key_a2', public.create_project_api_key(current_setting('test.pa')::uuid, 'second'), true);
select set_config('request.jwt.claims', '{"sub":"bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb","role":"authenticated"}', true);
select set_config('test.pb', (public.create_project('Project B')).id::text, true);
select set_config('test.key_b', public.create_project_api_key(current_setting('test.pb')::uuid, 'laptop'), true);

-- An unverified user who somehow holds a key (verified at creation, then changed) is refused.
reset role;
insert into public.profiles (id) values ('dddddddd-dddd-dddd-dddd-dddddddddddd') on conflict do nothing;

-- 1. The tables are invisible to clients; the functions are what they are allowed to call.
set local role anon;
select set_config('request.jwt.claims', '{"role":"anon"}', true);
do $$ begin
  begin perform * from private.usage_ledger; raise exception 'FAIL: ledger readable';
  exception when insufficient_privilege then null; end;
  begin perform * from private.usage_totals; raise exception 'FAIL: totals readable';
  exception when insufficient_privilege then null; end;
  begin perform * from private.quota_policies; raise exception 'FAIL: policies readable';
  exception when insufficient_privilege then null; end;
  begin perform private.quota_key_owner('x'); raise exception 'FAIL: private helper callable';
  exception when insufficient_privilege then null; end;
  begin perform public.my_quota(); raise exception 'FAIL: anon my_quota';
  exception when insufficient_privilege then null; end;
end $$;

-- 2. Bad keys are refused the same way, before anything is counted.
do $$ begin
  begin perform pg_temp.rq('nonsense', gen_random_uuid()); raise exception 'FAIL: malformed key';
  exception when sqlstate 'PT401' then null; end;
  begin perform pg_temp.rq('dw_' || repeat('0', 10) || '_' || repeat('0', 64), gen_random_uuid()); raise exception 'FAIL: unknown key';
  exception when sqlstate 'PT401' then null; end;
  begin perform pg_temp.rq(null, gen_random_uuid()); raise exception 'FAIL: null key';
  exception when sqlstate 'PT401' then null; end;
  begin perform pg_temp.rq(current_setting('test.key_a'), null); raise exception 'FAIL: null idempotency key';
  exception when sqlstate 'PT422' then null; end;
  begin perform pg_temp.sq(current_setting('test.key_a'), gen_random_uuid(), 'maybe'); raise exception 'FAIL: bad outcome';
  exception when sqlstate 'PT422' then null; end;
end $$;


-- 2b. Only the relay may meter: a project key alone cannot reserve or refund (the refund trick would be free calls).
do $$ begin
  begin perform public.reserve_quota(current_setting('test.key_a'), gen_random_uuid(), 'wrong'); raise exception 'FAIL: wrong relay secret reserved';
  exception when sqlstate 'PT401' then null; end;
  begin perform public.reserve_quota(current_setting('test.key_a'), gen_random_uuid(), null); raise exception 'FAIL: null relay secret reserved';
  exception when sqlstate 'PT401' then null; end;
  begin perform public.settle_quota(current_setting('test.key_a'), gen_random_uuid(), 'failed', 'wrong'); raise exception 'FAIL: wrong relay secret settled';
  exception when sqlstate 'PT401' then null; end;
end $$;

-- 3. Reserve, replay, settle. A replay counts nothing; a second key of the same user shares the allowance.
select set_config('test.k1', gen_random_uuid()::text, true);
select set_config('test.r1', pg_temp.rq(current_setting('test.key_a'), current_setting('test.k1')::uuid)::text, true);
do $$
declare r jsonb := current_setting('test.r1')::jsonb; rr jsonb; r2 jsonb;
begin
  if (r ->> 'used')::int <> 1 or (r ->> 'cap')::int <> 50 or (r ->> 'remaining')::int <> 49 or (r ->> 'replay')::boolean then
    raise exception 'FAIL: first reserve %', r; end if;
  rr := pg_temp.rq(current_setting('test.key_a'), current_setting('test.k1')::uuid);
  if not (rr ->> 'replay')::boolean or (rr ->> 'used')::int <> 1 then raise exception 'FAIL: replay counted %', rr; end if;
  r2 := pg_temp.rq(current_setting('test.key_a2'), gen_random_uuid());
  if (r2 ->> 'used')::int <> 2 then raise exception 'FAIL: same user, other key, separate allowance %', r2; end if;
  r2 := pg_temp.sq(current_setting('test.key_a'), current_setting('test.k1')::uuid, 'ok');
  if (r2 ->> 'used')::int <> 2 then raise exception 'FAIL: ok settle changed the count %', r2; end if;
  r2 := pg_temp.sq(current_setting('test.key_a'), current_setting('test.k1')::uuid, 'failed');
  if (r2 ->> 'used')::int <> 2 then raise exception 'FAIL: a settled unit was refunded later %', r2; end if;
end $$;

-- 4. A provider failure refunds the unit once; settling twice does not refund twice.
select set_config('test.k2', gen_random_uuid()::text, true);
do $$
declare r jsonb;
begin
  perform pg_temp.rq(current_setting('test.key_a'), current_setting('test.k2')::uuid);  -- used 3
  r := pg_temp.sq(current_setting('test.key_a'), current_setting('test.k2')::uuid, 'failed');
  if (r ->> 'used')::int <> 2 then raise exception 'FAIL: refund missing %', r; end if;
  r := pg_temp.sq(current_setting('test.key_a'), current_setting('test.k2')::uuid, 'failed');
  if (r ->> 'used')::int <> 2 then raise exception 'FAIL: refunded twice %', r; end if;
  r := pg_temp.sq(current_setting('test.key_a'), gen_random_uuid(), 'failed');  -- unknown reservation: no effect
  if (r ->> 'used')::int <> 2 then raise exception 'FAIL: unknown reservation changed the count %', r; end if;
end $$;

-- 5. Users are separate: B is untouched by A.
do $$
declare r jsonb := pg_temp.rq(current_setting('test.key_b'), gen_random_uuid());
begin
  if (r ->> 'used')::int <> 1 then raise exception 'FAIL: B shares the allowance with A %', r; end if;
end $$;

-- 6. The cap is hard. (Lower it to 4, as the owner would with an update.)
reset role;
update private.quota_policies set per_user_cap = 4 where name = 'free';
set local role anon;
select set_config('request.jwt.claims', '{"role":"anon"}', true);
do $$
declare r jsonb;
begin
  perform pg_temp.rq(current_setting('test.key_a'), gen_random_uuid());  -- 3
  r := pg_temp.rq(current_setting('test.key_a'), gen_random_uuid());     -- 4
  if (r ->> 'remaining')::int <> 0 then raise exception 'FAIL: remaining at cap %', r; end if;
  begin perform pg_temp.rq(current_setting('test.key_a'), gen_random_uuid()); raise exception 'FAIL: reserved past the cap';
  exception when sqlstate 'PT429' then null; end;
end $$;
reset role;
do $$ begin
  if (select used from private.usage_totals where user_id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa') <> 4 then
    raise exception 'FAIL: a refused reserve left a counter changed'; end if;
  if (select count(*) from private.usage_ledger where user_id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa' and state <> 'refunded') <> 4 then
    raise exception 'FAIL: a refused reserve left a ledger row'; end if;
end $$;

-- 7. The global daily budget: when it is full everyone is refused, and nothing is left half counted.
update private.quota_policies set per_user_cap = 50, global_daily_cap = (select used from private.usage_daily where day = current_date)
  where name = 'free';
set local role anon;
select set_config('request.jwt.claims', '{"role":"anon"}', true);
do $$ begin
  begin perform pg_temp.rq(current_setting('test.key_b'), gen_random_uuid()); raise exception 'FAIL: reserved past the daily budget';
  exception when sqlstate 'PT503' then null; end;
end $$;
reset role;
do $$ begin
  if (select used from private.usage_totals where user_id = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb') <> 1 then
    raise exception 'FAIL: the user counter moved although the daily budget refused'; end if;
end $$;

-- 8. The kill switch.
update private.quota_policies set global_daily_cap = 500, enabled = false where name = 'free';
set local role anon;
select set_config('request.jwt.claims', '{"role":"anon"}', true);
do $$ begin
  begin perform pg_temp.rq(current_setting('test.key_b'), gen_random_uuid()); raise exception 'FAIL: reserved while switched off';
  exception when sqlstate 'PT503' then null; end;
end $$;
reset role;
update private.quota_policies set enabled = true where name = 'free';

-- 8b. Fail closed: with no secret hash configured nothing can be metered, whatever secret is sent.
reset role;
update private.quota_policies set relay_secret_hash = null where name = 'free';
set local role anon;
select set_config('request.jwt.claims', '{"role":"anon"}', true);
do $$ begin
  begin perform public.reserve_quota(current_setting('test.key_b'), gen_random_uuid(), 'relay-secret'); raise exception 'FAIL: metered with no secret configured';
  exception when sqlstate 'PT401' then null; end;
end $$;
reset role;
update private.quota_policies set relay_secret_hash = extensions.digest('relay-secret', 'sha256') where name = 'free';

-- 9. A revoked key and an unverified email are refused.
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb","role":"authenticated"}', true);
select public.revoke_project_api_key((select id from public.project_api_keys limit 1));
set local role anon;
select set_config('request.jwt.claims', '{"role":"anon"}', true);
do $$ begin
  begin perform pg_temp.rq(current_setting('test.key_b'), gen_random_uuid()); raise exception 'FAIL: revoked key reserved';
  exception when sqlstate 'PT401' then null; end;
end $$;
reset role;
update auth.users set email_confirmed_at = null where id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';
set local role anon;
select set_config('request.jwt.claims', '{"role":"anon"}', true);
do $$ begin
  begin perform pg_temp.rq(current_setting('test.key_a'), gen_random_uuid()); raise exception 'FAIL: unverified user reserved';
  exception when sqlstate 'PT403' then null; end;
end $$;
reset role;
update auth.users set email_confirmed_at = now() where id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';

-- 10. A reservation nobody settled for 15 minutes is refunded by the user's next reserve.
update private.quota_policies set per_user_cap = 50 where name = 'free';
update private.usage_ledger set created_at = now() - interval '20 minutes' where state = 'reserved'
  and user_id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';
do $$ declare before int; stale int; r jsonb;
begin
  select used into before from private.usage_totals where user_id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';
  select count(*) into stale from private.usage_ledger where state = 'reserved' and user_id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';
  set local role anon;
  perform set_config('request.jwt.claims', '{"role":"anon"}', true);
  r := pg_temp.rq(current_setting('test.key_a'), gen_random_uuid());
  reset role;
  if (r ->> 'used')::int <> before - stale + 1 then raise exception 'FAIL: stale reservations not refunded (% -> %, stale %)', before, r, stale; end if;
end $$;

-- 11. The owner can read their own numbers; nobody else's.
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb","role":"authenticated"}', true);
do $$ declare q jsonb := public.my_quota(); begin
  if (q ->> 'used')::int <> 1 or (q ->> 'cap')::int <> 50 or not (q ->> 'enabled')::boolean then
    raise exception 'FAIL: my_quota for B %', q; end if;
end $$;

select 'PASS' as result;
rollback;
