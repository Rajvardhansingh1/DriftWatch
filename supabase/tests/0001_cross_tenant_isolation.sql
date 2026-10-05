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

select set_config('test.org_a', (public.create_organization('Org A')).id::text, true);
insert into public.projects (organization_id, name)
values (current_setting('test.org_a')::uuid, 'Project A');

select set_config('test.a_counts',
  (select count(*) from public.organizations) || ',' ||
  (select count(*) from public.organization_members) || ',' ||
  (select count(*) from public.projects), true);

select set_config('request.jwt.claims',
  '{"sub":"22222222-2222-2222-2222-222222222222","role":"authenticated"}', true);

select
  current_setting('test.a_counts') as a_orgs_members_projects,
  (select count(*) from public.organizations) as b_orgs,
  (select count(*) from public.organization_members) as b_members,
  (select count(*) from public.projects) as b_projects;

rollback;
