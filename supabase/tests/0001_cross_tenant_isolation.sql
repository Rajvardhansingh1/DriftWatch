-- Cross-tenant RLS isolation test for 0001/0002 migrations.
-- Run manually via Supabase SQL editor or `supabase db execute` against
-- the DriftWatch project. Wrapped in begin/rollback so it leaves no data
-- behind. Blocked from automated execution in this session by the
-- Claude Code auto-mode permission classifier (execute_sql denied as a
-- "Modify Shared Resources" action) - see decision.md D-031.

begin;

insert into auth.users (id, email, raw_user_meta_data)
values
  ('11111111-1111-1111-1111-111111111111', 'user-a@test.local', '{}'::jsonb),
  ('22222222-2222-2222-2222-222222222222', 'user-b@test.local', '{}'::jsonb);

set local role authenticated;
set local request.jwt.claims = '{"sub":"11111111-1111-1111-1111-111111111111","role":"authenticated"}';

select public.create_organization('Org A') as org_a \gset
insert into public.projects (organization_id, name) values (:'org_a_id', 'Project A');

-- Expect: user A sees exactly 1 org, 1 membership row (themself, owner), 1 project.
select
  (select count(*) from public.organizations) as orgs_visible_to_a,
  (select count(*) from public.organization_members) as members_visible_to_a,
  (select count(*) from public.projects) as projects_visible_to_a;

set local request.jwt.claims = '{"sub":"22222222-2222-2222-2222-222222222222","role":"authenticated"}';

-- Expect: user B (not a member of Org A) sees zero rows in all three -
-- this is the cross-tenant denial assertion.
select
  (select count(*) from public.organizations) as orgs_visible_to_b,
  (select count(*) from public.organization_members) as members_visible_to_b,
  (select count(*) from public.projects) as projects_visible_to_b;

-- Expect: user B cannot insert a project into Org A's org (RLS denies,
-- raises "new row violates row-level security policy").
-- select public.create_organization('Org B') as org_b \gset
-- insert into public.projects (organization_id, name) values (:'org_a_id', 'Project A hijack');

rollback;
