-- 0008: console functions: atomic project creation, account export, account deletion.

create function public.create_project(p_name text)
returns public.projects
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_uid uuid := (select auth.uid());
  v_org uuid;
  v_name text := btrim(p_name);
  v_project public.projects;
begin
  if v_uid is null then
    raise exception 'authentication required' using errcode = 'PT401';
  end if;
  if v_name is null or char_length(v_name) not between 1 and 64 then
    raise exception 'project name must be 1 to 64 characters' using errcode = 'PT422';
  end if;

  -- Serialise per user: keeps the project limit and the single personal org race-free.
  perform pg_advisory_xact_lock(hashtextextended(v_uid::text, 0));

  select organization_id into v_org
  from public.organization_members
  where user_id = v_uid and role = 'owner' and status = 'active'
  order by created_at
  limit 1;

  if v_org is null then
    insert into public.organizations (name, created_by) values ('Personal', v_uid)
      returning id into v_org;
    insert into public.organization_members (organization_id, user_id, role)
      values (v_org, v_uid, 'owner');
  end if;

  if (select count(*) from public.projects where organization_id = v_org) >= 5 then
    raise exception 'project limit reached' using errcode = 'PT422';
  end if;

  insert into public.projects (organization_id, name) values (v_org, v_name)
    returning * into v_project;
  perform private.write_audit(v_uid, v_org, 'project.create', v_project.id::text, 'ok');
  return v_project;
end;
$$;
revoke all on function public.create_project(text) from public, anon;
grant execute on function public.create_project(text) to authenticated;

create function public.delete_my_account()
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_uid uuid := (select auth.uid());
begin
  if v_uid is null then
    raise exception 'authentication required' using errcode = 'PT401';
  end if;

  if exists (
    select 1
    from public.organizations o
    join public.organization_members m on m.organization_id = o.id
    where o.created_by = v_uid and m.user_id <> v_uid and m.status = 'active'
  ) then
    raise exception 'transfer or remove the other members first' using errcode = 'PT422';
  end if;

  -- Anonymised: no actor, no target.
  perform private.write_audit(null, null, 'account.delete', null, 'ok');

  -- Cascades to members, projects, api keys, signals and hourly rows.
  delete from public.organizations where created_by = v_uid;
  -- Keys this user created inside someone else's organization (no FK cascade).
  delete from public.project_api_keys where created_by = v_uid;
  -- Cascades to the profile and any remaining memberships.
  delete from auth.users where id = v_uid;
end;
$$;
revoke all on function public.delete_my_account() from public, anon;
grant execute on function public.delete_my_account() to authenticated;

-- Security INVOKER on purpose: row-level security decides what the caller can read.
create function public.export_my_data()
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
  select jsonb_build_object(
    'exported_at', now(),
    'profile', (select to_jsonb(p) from public.profiles p where p.id = (select auth.uid())),
    'organizations', coalesce((select jsonb_agg(to_jsonb(o)) from public.organizations o), '[]'::jsonb),
    'memberships', coalesce((select jsonb_agg(to_jsonb(m)) from public.organization_members m), '[]'::jsonb),
    'projects', coalesce((select jsonb_agg(to_jsonb(pr)) from public.projects pr), '[]'::jsonb),
    'api_keys', coalesce((
      select jsonb_agg(jsonb_build_object(
        'id', k.id, 'project_id', k.project_id, 'name', k.name, 'prefix', k.prefix,
        'created_at', k.created_at, 'last_used_at', k.last_used_at, 'revoked_at', k.revoked_at))
      from public.project_api_keys k), '[]'::jsonb),
    'signal_records_latest_20000', coalesce((
      select jsonb_agg(to_jsonb(r))
      from (select * from public.signal_records
            where project_id in (select id from public.projects)
            order by occurred_at desc limit 20000) r), '[]'::jsonb),
    'signal_hourly', coalesce((select jsonb_agg(to_jsonb(h)) from public.signal_hourly h), '[]'::jsonb),
    'audit_events', coalesce((select jsonb_agg(to_jsonb(a)) from public.audit_events a), '[]'::jsonb)
  );
$$;
revoke all on function public.export_my_data() from public, anon;
grant execute on function public.export_my_data() to authenticated;
