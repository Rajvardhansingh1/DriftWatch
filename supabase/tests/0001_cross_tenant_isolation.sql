-- Cross-tenant RLS isolation test for 0001/0002 migrations.
-- Paste into the Supabase SQL editor and run. Plain SQL (no psql \gset):
-- values are carried between statements with set_config, and everything is
-- reported in ONE final row because the editor shows only the last result.
-- Wrapped in begin/rollback so it leaves no data behind.
--
-- PASS = a_orgs=1, a_members=1, a_projects=1, b_orgs=0, b_members=0, b_projects=0.

begin;

insert into auth.users (id, email, raw_user_meta_data)
values
  ('11111111-1111-1111-1111-111111111111', 'user-a@test.local', '{}'::jsonb),
  ('22222222-2222-2222-2222-222222222222', 'user-b@test.local', '{}'::jsonb);

set local role authenticated;
select set_config('request.jwt.claims',
  '{"sub":"11111111-1111-1111-1111-111111111111","role":"authenticated"}', true);

-- Projects are created only through create_project (0008), which also makes the personal org.
select set_config('test.proj_a', (public.create_project('Project A')).id::text, true);

select set_config('test.a_counts',
  (select count(*) from public.organizations) || ',' ||
  (select count(*) from public.organization_members) || ',' ||
  (select count(*) from public.projects), true);

select set_config('request.jwt.claims',
  '{"sub":"22222222-2222-2222-2222-222222222222","role":"authenticated"}', true);

-- User A sees exactly their own org, membership and project; user B, who owns nothing, sees none of A's.
select case
  when current_setting('test.a_counts') = '1,1,1'
   and (select count(*) from public.organizations) = 0
   and (select count(*) from public.organization_members) = 0
   and (select count(*) from public.projects) = 0
  then 'PASS'
  else 'FAIL: a=' || current_setting('test.a_counts') || ' b=' ||
       (select count(*) from public.organizations) || ',' ||
       (select count(*) from public.organization_members) || ',' ||
       (select count(*) from public.projects)
end;

rollback;
