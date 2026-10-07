-- Reverts 0005 except security revocations.
drop trigger if exists signal_records_guard on public.signal_records;
drop function if exists private.signal_records_guard();
alter table public.signal_records
  drop constraint if exists signal_records_signal_check,
  drop constraint if exists signal_records_value_check,
  drop constraint if exists signal_records_meta_size_check;
grant insert on public.signal_records to authenticated;

drop function if exists private.write_audit(uuid, uuid, text, text, text);
drop policy if exists "audit_events_select_org_admin" on public.audit_events;
revoke select on public.audit_events from authenticated;
drop index if exists public.audit_events_org_idx;
alter table public.audit_events drop column if exists organization_id, drop column if exists target;
drop index if exists public.organizations_created_by_idx;

drop policy "org_members_delete_admin_or_self" on public.organization_members;
create policy "org_members_delete_admin_or_self" on public.organization_members
  for delete using (private.is_org_member(organization_id, 'admin') or user_id = auth.uid());
drop policy "profiles_select_own" on public.profiles;
drop policy "profiles_update_own" on public.profiles;
create policy "profiles_select_own" on public.profiles for select using (id = auth.uid());
create policy "profiles_update_own" on public.profiles
  for update using (id = auth.uid()) with check (id = auth.uid());
