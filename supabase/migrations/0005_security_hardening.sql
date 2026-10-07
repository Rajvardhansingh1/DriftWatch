-- 0005: security hardening from Docs/superpowers/specs/2026-10-06-driftwatch-hardening-review.md
-- (A1, A2, A3, A4, A7). Tightening only; no data is touched.

-- A1: rls_auto_enable() is a platform helper that must never be an RPC.
do $$
begin
  if to_regprocedure('public.rls_auto_enable()') is not null then
    revoke execute on function public.rls_auto_enable() from public, anon, authenticated;
  end if;
end $$;

-- A2: create_organization is for signed-in users only.
revoke execute on function public.create_organization(text) from public, anon;
grant execute on function public.create_organization(text) to authenticated;

-- A4: evaluate auth.uid() once per statement, not once per row.
drop policy "profiles_select_own" on public.profiles;
drop policy "profiles_update_own" on public.profiles;
create policy "profiles_select_own" on public.profiles
  for select using (id = (select auth.uid()));
create policy "profiles_update_own" on public.profiles
  for update using (id = (select auth.uid())) with check (id = (select auth.uid()));

drop policy "org_members_delete_admin_or_self" on public.organization_members;
create policy "org_members_delete_admin_or_self" on public.organization_members
  for delete using (
    private.is_org_member(organization_id, 'admin') or user_id = (select auth.uid())
  );

create index organizations_created_by_idx on public.organizations (created_by);

-- A3: the audit trail gets a write path and an org-admin read path.
alter table public.audit_events
  add column organization_id uuid references public.organizations (id) on delete set null,
  add column target text;

create index audit_events_org_idx on public.audit_events (organization_id, occurred_at desc);

grant select on public.audit_events to authenticated;
create policy "audit_events_select_org_admin" on public.audit_events
  for select using (organization_id is not null and private.is_org_member(organization_id, 'admin'));
-- No insert/update/delete policy and no grant: only security-definer code writes.

create function private.write_audit(
  p_actor uuid, p_org uuid, p_action text, p_target text, p_result text
) returns void
language sql
security definer
set search_path = ''
as $$
  insert into public.audit_events (actor_user_id, organization_id, action, target, result)
  values (p_actor, p_org, p_action, p_target, p_result);
$$;
revoke all on function private.write_audit(uuid, uuid, text, text, text) from public, anon, authenticated;

-- R4: Supabase grants anon full table privileges by default; RLS alone would
-- return zero rows. Remove the privileges so anon gets a hard denial.
revoke all on public.signal_records from anon;

-- A7: clients may set only the observation fields; the server owns id and received_at.
revoke insert on public.signal_records from authenticated;
grant insert (project_id, event_id, signal, value, meta, occurred_at)
  on public.signal_records to authenticated;

alter table public.signal_records
  add constraint signal_records_signal_check check (signal in (
    'embedding_drift', 'self_consistency', 'canary_accuracy',
    'judge_trend', 'hallucination_score', 'combined_score')),
  add constraint signal_records_value_check check (value > -1e9 and value < 1e9),
  add constraint signal_records_meta_size_check check (pg_column_size(meta) <= 8192);

create function private.signal_records_guard() returns trigger
language plpgsql
set search_path = ''
as $$
begin
  -- Imported legacy rows (legacy_signal_id set) are exempt from the window.
  if new.legacy_signal_id is null
     and (new.occurred_at < now() - interval '30 days'
          or new.occurred_at > now() + interval '5 minutes') then
    raise exception 'occurred_at out of range' using errcode = 'PT422';
  end if;
  new.received_at := now();
  return new;
end;
$$;

create trigger signal_records_guard
  before insert on public.signal_records
  for each row execute function private.signal_records_guard();
