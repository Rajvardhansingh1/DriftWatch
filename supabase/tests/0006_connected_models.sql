-- PASS = a single row with result = 'PASS'. Any 'FAIL: ...' error is a bug. Leaves no data (rolled back).
begin;

insert into auth.users (id, email, email_confirmed_at, raw_user_meta_data) values
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'a@test.local', now(), '{}'::jsonb),
  ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 'b@test.local', now(), '{}'::jsonb);

set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa","role":"authenticated"}', true);
select set_config('test.pa', (public.create_project('Project A')).id::text, true);
select set_config('request.jwt.claims', '{"sub":"bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb","role":"authenticated"}', true);
select set_config('test.pb', (public.create_project('Project B')).id::text, true);

-- Helpers: the runner secret, base64 test material, a connect call.
reset role;
update private.runner_policy set runner_secret_hash = extensions.digest('runner-secret', 'sha256');
create function pg_temp.connect(p_project uuid, p_model uuid, p_provider text default 'groq', p_interval int default 60, p_budget int default 2000)
returns void language sql as $f$
  select public.connect_model(p_project, p_model, p_provider, 'some-model', 'wxyz', 1,
    encode(decode(repeat('ab', 32), 'hex'), 'base64'), encode(decode(repeat('cd', 12), 'hex'), 'base64'),
    encode(decode(repeat('ef', 40), 'hex'), 'base64'), p_interval, p_budget)
$f$;
grant execute on function pg_temp.connect(uuid, uuid, text, int, int) to authenticated;

-- 1. Dark by default: nothing can be connected until the owner switches it on.
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa","role":"authenticated"}', true);
do $$ begin
  begin perform pg_temp.connect(current_setting('test.pa')::uuid, gen_random_uuid()); raise exception 'FAIL: connected while switched off';
  exception when sqlstate 'PT503' then null; end;
end $$;
reset role;
update private.runner_policy set enabled = true;

-- 2. Who may connect, and what is refused.
set local role authenticated;
select set_config('test.m1', gen_random_uuid()::text, true);
do $$ begin
  begin perform pg_temp.connect(current_setting('test.pb')::uuid, gen_random_uuid()); raise exception 'FAIL: A connected a model on B''s project';
  exception when sqlstate 'PT403' then null; end;
  begin perform pg_temp.connect(current_setting('test.pa')::uuid, gen_random_uuid(), 'anthropic'); raise exception 'FAIL: provider outside the allow-list';
  exception when sqlstate 'PT422' then null; end;
  begin perform pg_temp.connect(current_setting('test.pa')::uuid, gen_random_uuid(), 'groq', 5); raise exception 'FAIL: interval under 15 minutes';
  exception when sqlstate 'PT422' then null; end;
  begin perform pg_temp.connect(current_setting('test.pa')::uuid, gen_random_uuid(), 'groq', 60, 0); raise exception 'FAIL: zero budget';
  exception when sqlstate 'PT422' then null; end;
  begin perform public.connect_model(current_setting('test.pa')::uuid, gen_random_uuid(), 'groq', 'm', 'abcd', 1, '!!!not base64!!!', 'x', 'y');
    raise exception 'FAIL: bad base64 accepted';
  exception when sqlstate 'PT422' then null; end;
  begin perform public.connect_model(current_setting('test.pa')::uuid, gen_random_uuid(), 'groq', 'bad model name', 'abcd', 1,
      encode(decode(repeat('ab', 32), 'hex'), 'base64'), encode(decode(repeat('cd', 12), 'hex'), 'base64'), encode(decode(repeat('ef', 40), 'hex'), 'base64'));
    raise exception 'FAIL: model name with spaces';
  exception when sqlstate 'PT422' then null; end;
  if (select count(*) from public.connected_models) <> 0 then raise exception 'FAIL: a refused connect left a row'; end if;
end $$;
select pg_temp.connect(current_setting('test.pa')::uuid, current_setting('test.m1')::uuid);

-- 3. Visibility: the member sees settings, never secrets; B and anon see nothing.
do $$ declare c record; begin
  select * into c from public.connected_models;
  if c.provider <> 'groq' or c.last4 <> 'wxyz' or c.interval_minutes <> 60 or c.monthly_budget <> 2000 then raise exception 'FAIL: settings wrong'; end if;
  begin perform * from private.connected_secrets; raise exception 'FAIL: A can read the ciphertext';
  exception when insufficient_privilege then null; end;
  begin perform * from private.connected_jobs; raise exception 'FAIL: A can read jobs';
  exception when insufficient_privilege then null; end;
  begin perform * from private.probe_vectors; raise exception 'FAIL: A can read vectors';
  exception when insufficient_privilege then null; end;
  begin perform * from private.runner_audit; raise exception 'FAIL: A can read the audit trail';
  exception when insufficient_privilege then null; end;
  begin perform * from private.runner_policy; raise exception 'FAIL: A can read the runner policy';
  exception when insufficient_privilege then null; end;
  begin insert into public.connected_models (id, project_id, provider, model, last4, created_by) values (gen_random_uuid(), current_setting('test.pa')::uuid, 'groq', 'm', 'abcd', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa');
    raise exception 'FAIL: direct insert allowed';
  exception when insufficient_privilege then null; end;
  begin update public.connected_models set provider = 'openai'; raise exception 'FAIL: direct update allowed';
  exception when insufficient_privilege then null; end;
  begin perform public.runner_claim_jobs('x'); raise exception 'FAIL: A called a runner function';
  exception when insufficient_privilege then null; when sqlstate 'PT401' then null; end;
end $$;
select set_config('request.jwt.claims', '{"sub":"bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb","role":"authenticated"}', true);
do $$ begin
  if (select count(*) from public.connected_models) <> 0 then raise exception 'FAIL: B sees A''s model'; end if;
  begin perform public.delete_connected_model(current_setting('test.pa')::uuid); raise exception 'FAIL: B deleted A''s model';
  exception when sqlstate 'PT403' then null; end;
  begin perform public.set_probes(current_setting('test.pa')::uuid, '[{"prompt":"p","expected":"e"}]'::jsonb); raise exception 'FAIL: B set A''s probes';
  exception when sqlstate 'PT403' then null; end;
  begin perform public.update_connected_model(current_setting('test.pa')::uuid, 30, 100, true); raise exception 'FAIL: B changed A''s settings';
  exception when sqlstate 'PT403' then null; end;
end $$;
set local role anon;
select set_config('request.jwt.claims', '{"role":"anon"}', true);
do $$ begin
  begin perform * from public.connected_models; raise exception 'FAIL: anon reads models';
  exception when insufficient_privilege then null; end;
end $$;

-- 4. Probes: validation, then a real set.
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa","role":"authenticated"}', true);
do $$ begin
  begin perform public.set_probes(current_setting('test.pa')::uuid, '[]'::jsonb); raise exception 'FAIL: zero probes';
  exception when sqlstate 'PT422' then null; end;
  begin perform public.set_probes(current_setting('test.pa')::uuid, (select jsonb_agg(jsonb_build_object('prompt', 'p' || i, 'expected', 'e')) from generate_series(1, 6) i));
    raise exception 'FAIL: six probes';
  exception when sqlstate 'PT422' then null; end;
  begin perform public.set_probes(current_setting('test.pa')::uuid, '[{"prompt":"p","expected":"e","match_type":"regex"}]'::jsonb); raise exception 'FAIL: unknown match type';
  exception when sqlstate 'PT422' then null; end;
  begin perform public.set_probes(current_setting('test.pa')::uuid, '[{"expected":"e"}]'::jsonb); raise exception 'FAIL: probe without a prompt';
  exception when sqlstate 'PT422' then null; end;
  begin perform public.set_probes(current_setting('test.pa')::uuid, jsonb_build_array(jsonb_build_object('prompt', repeat('x', 501), 'expected', 'e'))); raise exception 'FAIL: oversized prompt';
  exception when sqlstate 'PT422' then null; end;
end $$;
select public.set_probes(current_setting('test.pa')::uuid, '[{"prompt":"What is 2+2?","expected":"4"},{"prompt":"Capital of France?","expected":"Paris","match_type":"exact"},{"prompt":"Say OK","expected":"OK"}]'::jsonb);
do $$ begin
  if (select count(*) from public.connected_probes) <> 3 then raise exception 'FAIL: probes not stored'; end if;
end $$;

-- 5. The runner: every function refuses a wrong or missing secret.
set local role anon;
select set_config('request.jwt.claims', '{"role":"anon"}', true);
do $$ declare fake uuid := gen_random_uuid(); begin
  begin perform public.runner_claim_jobs('wrong'); raise exception 'FAIL: claim with a wrong secret'; exception when sqlstate 'PT401' then null; end;
  begin perform public.runner_claim_jobs(null); raise exception 'FAIL: claim with no secret'; exception when sqlstate 'PT401' then null; end;
  begin perform public.runner_get_secret('wrong', fake, fake); raise exception 'FAIL: get_secret with a wrong secret'; exception when sqlstate 'PT401' then null; end;
  begin perform public.runner_get_vectors('wrong', fake, fake); raise exception 'FAIL: get_vectors with a wrong secret'; exception when sqlstate 'PT401' then null; end;
  begin perform public.runner_save_vectors('wrong', fake, fake, '', '', 1); raise exception 'FAIL: save_vectors with a wrong secret'; exception when sqlstate 'PT401' then null; end;
  begin perform public.runner_write_signals('wrong', fake, fake, '[]'::jsonb); raise exception 'FAIL: write_signals with a wrong secret'; exception when sqlstate 'PT401' then null; end;
  begin perform public.runner_finish_job('wrong', fake, fake, 'ok', 1); raise exception 'FAIL: finish with a wrong secret'; exception when sqlstate 'PT401' then null; end;
  begin perform public.runner_health('wrong'); raise exception 'FAIL: health with a wrong secret'; exception when sqlstate 'PT401' then null; end;
end $$;

-- 6. Claim: one job with its probes and a lease; nobody else gets it; the secret needs the lease.
select set_config('test.claim', public.runner_claim_jobs('runner-secret')::text, true);
do $$ declare c jsonb := current_setting('test.claim')::jsonb; begin
  if jsonb_array_length(c) <> 1 then raise exception 'FAIL: claim should return one job: %', c; end if;
  if jsonb_array_length(c -> 0 -> 'probes') <> 3 or (c -> 0 ->> 'max_calls')::int <> 5 or c -> 0 ->> 'provider' <> 'groq' then raise exception 'FAIL: claim content %', c; end if;
  if jsonb_array_length(public.runner_claim_jobs('runner-secret')) <> 0 then raise exception 'FAIL: a leased job was claimed twice'; end if;
end $$;
select set_config('test.lease', (current_setting('test.claim')::jsonb -> 0 ->> 'lease'), true);
do $$ declare s jsonb; begin
  begin perform public.runner_get_secret('runner-secret', current_setting('test.m1')::uuid, gen_random_uuid()); raise exception 'FAIL: secret without the lease';
  exception when sqlstate 'PT409' then null; end;
  begin perform public.runner_get_secret('runner-secret', gen_random_uuid(), current_setting('test.lease')::uuid); raise exception 'FAIL: another model with this lease';
  exception when sqlstate 'PT409' then null; end;
  s := public.runner_get_secret('runner-secret', current_setting('test.m1')::uuid, current_setting('test.lease')::uuid);
  if (s ->> 'key_id')::int <> 1 or length(decode(s ->> 'ciphertext', 'base64')) <> 40 then raise exception 'FAIL: secret content %', s; end if;
end $$;
reset role;
do $$ begin
  if (select count(*) from private.runner_audit where action = 'decrypt') <> 1 then raise exception 'FAIL: one decrypt should leave one audit row'; end if;
  if (select count(*) from private.runner_audit where action = 'claim') <> 1 then raise exception 'FAIL: claim audit'; end if;
end $$;

-- 7. Vectors and signals through the lease.
set local role anon;
select set_config('request.jwt.claims', '{"role":"anon"}', true);
select public.runner_save_vectors('runner-secret', current_setting('test.m1')::uuid, current_setting('test.lease')::uuid,
  encode('baseline-bytes'::bytea, 'base64'), encode('recent-bytes'::bytea, 'base64'), 1);
do $$ declare v jsonb; n int; ev jsonb; begin
  v := public.runner_get_vectors('runner-secret', current_setting('test.m1')::uuid, current_setting('test.lease')::uuid);
  if convert_from(decode(v ->> 'baseline', 'base64'), 'utf8') <> 'baseline-bytes' or (v ->> 'runs')::int <> 1 then raise exception 'FAIL: vectors %', v; end if;
  ev := jsonb_build_array(
    jsonb_build_object('event_id', gen_random_uuid(), 'signal', 'canary_accuracy', 'value', 0.8, 'occurred_at', now(), 'meta', '{"probes": 3}'::jsonb),
    jsonb_build_object('event_id', gen_random_uuid(), 'signal', 'self_consistency', 'value', 0.1, 'occurred_at', now(), 'meta', '{}'::jsonb));
  n := public.runner_write_signals('runner-secret', current_setting('test.m1')::uuid, current_setting('test.lease')::uuid, ev);
  if n <> 2 then raise exception 'FAIL: two signals expected, got %', n; end if;
  if public.runner_write_signals('runner-secret', current_setting('test.m1')::uuid, current_setting('test.lease')::uuid, ev) <> 0 then raise exception 'FAIL: a replay was stored twice'; end if;
  begin perform public.runner_write_signals('runner-secret', current_setting('test.m1')::uuid, current_setting('test.lease')::uuid,
      jsonb_build_array(jsonb_build_object('event_id', gen_random_uuid(), 'signal', 'judge_trend', 'value', 0.5, 'occurred_at', now())));
    raise exception 'FAIL: a signal the runner may not write';
  exception when sqlstate 'PT422' then null; end;
  begin perform public.runner_write_signals('runner-secret', current_setting('test.m1')::uuid, current_setting('test.lease')::uuid,
      jsonb_build_array(jsonb_build_object('event_id', gen_random_uuid(), 'signal', 'canary_accuracy', 'value', 'NaN'::float8, 'occurred_at', now())));
    raise exception 'FAIL: NaN accepted';
  exception when sqlstate 'PT422' then null; end;
  begin perform public.runner_write_signals('runner-secret', current_setting('test.m1')::uuid, current_setting('test.lease')::uuid,
      jsonb_build_array(jsonb_build_object('event_id', gen_random_uuid(), 'signal', 'canary_accuracy', 'value', 0.5, 'occurred_at', now() + interval '1 hour')));
    raise exception 'FAIL: a future time accepted';
  exception when sqlstate 'PT422' then null; end;
  begin perform public.runner_write_signals('runner-secret', current_setting('test.m1')::uuid, current_setting('test.lease')::uuid,
      (select jsonb_agg(jsonb_build_object('event_id', gen_random_uuid(), 'signal', 'canary_accuracy', 'value', 0.5, 'occurred_at', now())) from generate_series(1, 11)));
    raise exception 'FAIL: eleven events accepted';
  exception when sqlstate 'PT422' then null; end;
end $$;
reset role;
do $$ begin
  if (select count(*) from public.signal_records where project_id = current_setting('test.pa')::uuid and meta ->> 'mode' = 'cloud_probe' and meta ->> 'source' = 'cloud_runner') <> 2 then
    raise exception 'FAIL: stored signals not labelled cloud_probe'; end if;
end $$;

-- 8. Finish ok: calls counted, next run scheduled; not claimable until due.
set local role anon;
select set_config('request.jwt.claims', '{"role":"anon"}', true);
select public.runner_finish_job('runner-secret', current_setting('test.m1')::uuid, current_setting('test.lease')::uuid, 'ok', 5);
do $$ begin
  begin perform public.runner_finish_job('runner-secret', current_setting('test.m1')::uuid, current_setting('test.lease')::uuid, 'ok', 5); raise exception 'FAIL: finished twice with one lease';
  exception when sqlstate 'PT409' then null; end;
  if jsonb_array_length(public.runner_claim_jobs('runner-secret')) <> 0 then raise exception 'FAIL: claimed before the next run is due'; end if;
end $$;
reset role;
do $$ begin
  if (select calls_this_month from public.connected_models) <> 5 or (select last_run_at from public.connected_models) is null or (select last_error from public.connected_models) is not null then
    raise exception 'FAIL: bookkeeping after a good run'; end if;
  if (select due_at from private.connected_jobs) < now() + interval '59 minutes' then raise exception 'FAIL: next run not scheduled one interval ahead'; end if;
end $$;

-- 9. Failures: one retry soon, then a dead letter; a rejected key is dead at once; the user's save revives it.
update private.connected_jobs set due_at = now();
set local role anon;
select set_config('request.jwt.claims', '{"role":"anon"}', true);
select set_config('test.lease', (public.runner_claim_jobs('runner-secret') -> 0 ->> 'lease'), true);
select public.runner_finish_job('runner-secret', current_setting('test.m1')::uuid, current_setting('test.lease')::uuid, 'provider_error', 2);
reset role;
do $$ begin
  if (select state from private.connected_jobs) <> 'idle' or (select due_at from private.connected_jobs) > now() + interval '6 minutes' then raise exception 'FAIL: first failure should retry soon'; end if;
  if (select last_error from public.connected_models) not like 'The provider did not answer%' then raise exception 'FAIL: fixed sentence expected'; end if;
end $$;
update private.connected_jobs set due_at = now();
set local role anon;
select set_config('request.jwt.claims', '{"role":"anon"}', true);
select set_config('test.lease', (public.runner_claim_jobs('runner-secret') -> 0 ->> 'lease'), true);
select public.runner_finish_job('runner-secret', current_setting('test.m1')::uuid, current_setting('test.lease')::uuid, 'bad_reply', 2);
reset role;
do $$ begin
  if (select state from private.connected_jobs) <> 'dead' then raise exception 'FAIL: the second failure should dead-letter'; end if;
end $$;
set local role anon;
select set_config('request.jwt.claims', '{"role":"anon"}', true);
do $$ begin
  if jsonb_array_length(public.runner_claim_jobs('runner-secret')) <> 0 then raise exception 'FAIL: a dead job was claimed'; end if;
end $$;
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa","role":"authenticated"}', true);
select public.update_connected_model(current_setting('test.pa')::uuid, 60, 2000, true);
reset role;
do $$ begin
  if (select state from private.connected_jobs) <> 'idle' or (select attempts from private.connected_jobs) <> 0 then raise exception 'FAIL: saving did not revive the job'; end if;
end $$;
set local role anon;
select set_config('request.jwt.claims', '{"role":"anon"}', true);
select set_config('test.lease', (public.runner_claim_jobs('runner-secret') -> 0 ->> 'lease'), true);
select public.runner_finish_job('runner-secret', current_setting('test.m1')::uuid, current_setting('test.lease')::uuid, 'provider_auth', 1);
reset role;
do $$ begin
  if (select state from private.connected_jobs) <> 'dead' or (select last_error from public.connected_models) not like 'The provider rejected the key%' then
    raise exception 'FAIL: a rejected key should dead-letter at once'; end if;
end $$;
set local role anon;
select set_config('request.jwt.claims', '{"role":"anon"}', true);
do $$ begin
  begin perform public.runner_finish_job('runner-secret', current_setting('test.m1')::uuid, current_setting('test.lease')::uuid, 'free text from a provider', 1);
    raise exception 'FAIL: arbitrary text accepted as an outcome';
  exception when sqlstate 'PT409' then null; when sqlstate 'PT422' then null; end;
end $$;

-- 10. Lease expiry: an expired lease is reclaimed once, then a dead letter.
reset role;
update private.connected_jobs set state = 'idle', attempts = 0, due_at = now(), lease_until = null, lease_token = null;
set local role anon;
select set_config('request.jwt.claims', '{"role":"anon"}', true);
select public.runner_claim_jobs('runner-secret');   -- attempt 1
reset role;
update private.connected_jobs set lease_until = now() - interval '1 minute';
set local role anon;
select set_config('request.jwt.claims', '{"role":"anon"}', true);
do $$ begin
  if jsonb_array_length(public.runner_claim_jobs('runner-secret')) <> 1 then raise exception 'FAIL: an expired lease should be reclaimed'; end if;  -- attempt 2
end $$;
reset role;
update private.connected_jobs set lease_until = now() - interval '1 minute';
set local role anon;
select set_config('request.jwt.claims', '{"role":"anon"}', true);
do $$ begin
  if jsonb_array_length(public.runner_claim_jobs('runner-secret')) <> 0 then raise exception 'FAIL: a twice-expired lease should not be claimed again'; end if;
end $$;
reset role;
do $$ begin
  if (select state from private.connected_jobs) <> 'dead' or (select last_error from public.connected_models) not like 'The runner could not finish%' then
    raise exception 'FAIL: a twice-expired lease should dead-letter with a sentence'; end if;
end $$;

-- 11. The monthly budget is enforced in the database.
update private.connected_jobs set state = 'idle', attempts = 0, due_at = now(), lease_until = null, lease_token = null;
update public.connected_models set monthly_budget = 6, calls_this_month = 3;   -- a run needs 5 calls: 3 + 5 > 6
set local role anon;
select set_config('request.jwt.claims', '{"role":"anon"}', true);
do $$ begin
  if jsonb_array_length(public.runner_claim_jobs('runner-secret')) <> 0 then raise exception 'FAIL: claimed past the monthly budget'; end if;
end $$;
reset role;
do $$ begin
  if (select last_error from public.connected_models) not like 'The monthly call budget%' then raise exception 'FAIL: budget sentence'; end if;
  if (select due_at from private.connected_jobs) < date_trunc('month', now()) + interval '1 month' then raise exception 'FAIL: not parked until next month'; end if;
end $$;

-- 12. The global switch and the health numbers.
update private.connected_jobs set due_at = now();
update public.connected_models set monthly_budget = 2000, calls_this_month = 0;
update private.runner_policy set enabled = false;
set local role anon;
select set_config('request.jwt.claims', '{"role":"anon"}', true);
do $$ declare h jsonb; begin
  if jsonb_array_length(public.runner_claim_jobs('runner-secret')) <> 0 then raise exception 'FAIL: claimed while switched off'; end if;
  h := public.runner_health('runner-secret');
  if (h ->> 'enabled')::boolean or (h ->> 'models')::int <> 1 or (h ->> 'decrypts_24h')::int < 1 then raise exception 'FAIL: health %', h; end if;
  if h::text like '%model_id%' or h::text like '%ciphertext%' then raise exception 'FAIL: health leaks identifiers'; end if;
  if (h -> 'key_ids' ->> '1')::int <> 1 then raise exception 'FAIL: health should count rows per key id %', h; end if;
end $$;
reset role;
update private.runner_policy set enabled = true;

-- 13. Fail closed: no secret hash configured means no runner call works, whatever is sent.
update private.runner_policy set runner_secret_hash = null;
set local role anon;
select set_config('request.jwt.claims', '{"role":"anon"}', true);
do $$ begin
  begin perform public.runner_claim_jobs('runner-secret'); raise exception 'FAIL: runner call with no secret configured';
  exception when sqlstate 'PT401' then null; end;
end $$;
reset role;
update private.runner_policy set runner_secret_hash = extensions.digest('runner-secret', 'sha256');

-- 14. Export has the settings, never a secret; delete removes everything; the audit trail survives.
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa","role":"authenticated"}', true);
do $$ declare e text := public.export_my_data()::text; begin
  if e not like '%connected_models%' or e not like '%wxyz%' then raise exception 'FAIL: export misses the connected model settings'; end if;
  if e like '%ciphertext%' or e like '%ephemeral%' or e like '%nonce%' or e like '%lease%' then raise exception 'FAIL: export contains secret material'; end if;
end $$;
select public.delete_connected_model(current_setting('test.pa')::uuid);
reset role;
do $$ begin
  if (select count(*) from public.connected_models) <> 0 or (select count(*) from private.connected_secrets) <> 0
     or (select count(*) from private.connected_jobs) <> 0 or (select count(*) from private.probe_vectors) <> 0 then
    raise exception 'FAIL: delete left something behind'; end if;
  if (select count(*) from private.runner_audit) < 3 then raise exception 'FAIL: the audit trail should outlive the model'; end if;
  if (select count(*) from public.audit_events where action in ('connected_model.create', 'connected_model.delete')) <> 2 then raise exception 'FAIL: user-facing audit'; end if;
end $$;

-- 15. Deleting the project removes a connected model too.
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa","role":"authenticated"}', true);
select pg_temp.connect(current_setting('test.pa')::uuid, gen_random_uuid());
reset role;
delete from public.projects where id = current_setting('test.pa')::uuid;
do $$ begin
  if (select count(*) from private.connected_secrets) <> 0 or (select count(*) from public.connected_models) <> 0 then
    raise exception 'FAIL: project delete left a connected model or its secret'; end if;
end $$;

select 'PASS' as result;
rollback;
