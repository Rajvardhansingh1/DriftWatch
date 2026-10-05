-- Hardening pass on 0001, driven by get_advisors(security) findings.
-- handle_new_user() is a trigger-only function - it should never be
-- directly callable as a PostgREST RPC. is_org_member() is an internal
-- RLS helper - it must stay callable BY the authenticated role so
-- policies can invoke it, but moving it to a non-exposed schema takes
-- it off the public REST surface (PostgREST only routes through
-- schemas in the exposed-schema list, which is just "public" here).

revoke execute on function public.handle_new_user() from public, anon, authenticated;

create schema if not exists private;
revoke all on schema private from public, anon, authenticated;
grant usage on schema private to authenticated;

create function private.is_org_member(p_org_id uuid, p_min_role text default 'viewer')
returns boolean
language sql
security definer
stable
set search_path = public
as $$
  select exists (
    select 1
    from public.organization_members m
    where m.organization_id = p_org_id
      and m.user_id = auth.uid()
      and m.status = 'active'
      and (
        case m.role
          when 'owner' then 4
          when 'admin' then 3
          when 'member' then 2
          else 1
        end
      ) >= (
        case p_min_role
          when 'owner' then 4
          when 'admin' then 3
          when 'member' then 2
          else 1
        end
      )
  );
$$;

grant execute on function private.is_org_member(uuid, text) to authenticated;
revoke execute on function private.is_org_member(uuid, text) from public, anon;

-- Repoint every policy from public.is_org_member to private.is_org_member.
drop policy "organizations_select_member" on public.organizations;
drop policy "organizations_update_owner" on public.organizations;
drop policy "organizations_delete_owner" on public.organizations;
drop policy "org_members_select_member" on public.organization_members;
drop policy "org_members_update_admin" on public.organization_members;
drop policy "org_members_delete_admin_or_self" on public.organization_members;
drop policy "projects_select_member" on public.projects;
drop policy "projects_insert_admin" on public.projects;
drop policy "projects_update_admin" on public.projects;
drop policy "projects_delete_owner" on public.projects;

create policy "organizations_select_member" on public.organizations
  for select using (private.is_org_member(id, 'viewer'));
create policy "organizations_update_owner" on public.organizations
  for update using (private.is_org_member(id, 'owner'))
  with check (private.is_org_member(id, 'owner'));
create policy "organizations_delete_owner" on public.organizations
  for delete using (private.is_org_member(id, 'owner'));

create policy "org_members_select_member" on public.organization_members
  for select using (private.is_org_member(organization_id, 'viewer'));
create policy "org_members_update_admin" on public.organization_members
  for update using (private.is_org_member(organization_id, 'admin'))
  with check (private.is_org_member(organization_id, 'admin'));
create policy "org_members_delete_admin_or_self" on public.organization_members
  for delete using (
    private.is_org_member(organization_id, 'admin') or user_id = auth.uid()
  );

create policy "projects_select_member" on public.projects
  for select using (private.is_org_member(organization_id, 'viewer'));
create policy "projects_insert_admin" on public.projects
  for insert with check (private.is_org_member(organization_id, 'admin'));
create policy "projects_update_admin" on public.projects
  for update using (private.is_org_member(organization_id, 'admin'))
  with check (private.is_org_member(organization_id, 'admin'));
create policy "projects_delete_owner" on public.projects
  for delete using (private.is_org_member(organization_id, 'owner'));

-- create_organization() stays public/exposed - that IS its purpose
-- (the one legitimate client-callable RPC in this migration). Drop the
-- now-unused public copy of the helper.
drop function public.is_org_member(uuid, text);
