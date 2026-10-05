-- DriftWatch upgrade Phase 2: Supabase foundation and tenancy.
-- Spec_Upgrade.md section 5 (accounts/orgs/projects/roles), section 6.4 (RLS).
-- Additive only. Applied to the confirmed "DriftWatch" project
-- (zaodlvgqowhdqobvvhpx, ap-southeast-2) only. See decision.md D-027/D-030.

-- ---------------------------------------------------------------------
-- profiles: 1:1 application profile keyed to auth.users
-- ---------------------------------------------------------------------
create table public.profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  display_name text,
  created_at timestamptz not null default now()
);

alter table public.profiles enable row level security;

create policy "profiles_select_own" on public.profiles
  for select using (id = auth.uid());

create policy "profiles_update_own" on public.profiles
  for update using (id = auth.uid()) with check (id = auth.uid());

-- No insert/delete policy: rows are created only by handle_new_user()
-- below (SECURITY DEFINER, bypasses RLS) and deleted only by the
-- auth.users cascade. Clients cannot create or remove a profile directly.

create function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id, display_name)
  values (new.id, new.raw_user_meta_data ->> 'display_name');
  return new;
end;
$$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ---------------------------------------------------------------------
-- organizations / organization_members: tenant root + membership+role
-- ---------------------------------------------------------------------
create table public.organizations (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  created_by uuid not null references public.profiles (id),
  created_at timestamptz not null default now()
);

create table public.organization_members (
  organization_id uuid not null references public.organizations (id) on delete cascade,
  user_id uuid not null references public.profiles (id) on delete cascade,
  role text not null check (role in ('owner', 'admin', 'member', 'viewer')),
  status text not null default 'active' check (status in ('active', 'invited', 'removed')),
  created_at timestamptz not null default now(),
  primary key (organization_id, user_id)
);

create index organization_members_user_id_idx on public.organization_members (user_id);

-- Role-rank helper: SECURITY DEFINER so it can be called from RLS
-- policies on organization_members/organizations/projects without
-- recursive-RLS deadlock. Rare, reviewed, schema-qualified search_path
-- per Spec_Upgrade.md section 6.4.
create function public.is_org_member(p_org_id uuid, p_min_role text default 'viewer')
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

-- Atomic org creation: the only way to create an organization or its
-- first membership row. Direct client INSERT on organizations/
-- organization_members is intentionally not permitted (see policies
-- below) so a client can never create an org without becoming its
-- owner, and can never self-assign a role outside this function.
create function public.create_organization(p_name text)
returns public.organizations
language plpgsql
security definer
set search_path = public
as $$
declare
  v_org public.organizations;
begin
  if auth.uid() is null then
    raise exception 'authentication required';
  end if;

  insert into public.organizations (name, created_by)
  values (p_name, auth.uid())
  returning * into v_org;

  insert into public.organization_members (organization_id, user_id, role)
  values (v_org.id, auth.uid(), 'owner');

  return v_org;
end;
$$;

alter table public.organizations enable row level security;
alter table public.organization_members enable row level security;

create policy "organizations_select_member" on public.organizations
  for select using (public.is_org_member(id, 'viewer'));

create policy "organizations_update_owner" on public.organizations
  for update using (public.is_org_member(id, 'owner'))
  with check (public.is_org_member(id, 'owner'));

create policy "organizations_delete_owner" on public.organizations
  for delete using (public.is_org_member(id, 'owner'));

-- No client INSERT policy on organizations: create_organization() is the
-- only creation path (SECURITY DEFINER bypasses RLS for its own insert).

create policy "org_members_select_member" on public.organization_members
  for select using (public.is_org_member(organization_id, 'viewer'));

create policy "org_members_update_admin" on public.organization_members
  for update using (public.is_org_member(organization_id, 'admin'))
  with check (public.is_org_member(organization_id, 'admin'));

create policy "org_members_delete_admin_or_self" on public.organization_members
  for delete using (
    public.is_org_member(organization_id, 'admin') or user_id = auth.uid()
  );

-- No client INSERT policy on organization_members: adding a member is a
-- Phase 2+ invite-flow feature, not built yet (YAGNI) - the only member
-- row today is the owner row create_organization() inserts.

-- ---------------------------------------------------------------------
-- projects: monitored application/project belonging to an organization
-- ---------------------------------------------------------------------
create table public.projects (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations (id) on delete cascade,
  name text not null,
  settings jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index projects_organization_id_idx on public.projects (organization_id);

alter table public.projects enable row level security;

create policy "projects_select_member" on public.projects
  for select using (public.is_org_member(organization_id, 'viewer'));

create policy "projects_insert_admin" on public.projects
  for insert with check (public.is_org_member(organization_id, 'admin'));

create policy "projects_update_admin" on public.projects
  for update using (public.is_org_member(organization_id, 'admin'))
  with check (public.is_org_member(organization_id, 'admin'));

create policy "projects_delete_owner" on public.projects
  for delete using (public.is_org_member(organization_id, 'owner'));
