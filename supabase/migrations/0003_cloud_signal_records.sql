-- Cloud counterpart of the local signal_records table (Docs/Phase_Upgrade_Guide.md
-- section 4.1/5). project_id/RLS are new - the local table has neither.
-- legacy_signal_id is set only for rows imported from a local SQLite
-- file by scripts/migrate_sqlite_to_supabase.py (Phase 3); native
-- cloud-created rows leave it null. Postgres treats multiple NULLs in a
-- unique constraint as distinct, so this does not block ordinary inserts -
-- it only makes a re-run of the migration script idempotent per source row.

create table public.signal_records (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects (id) on delete cascade,
  signal text not null,
  value double precision not null,
  meta jsonb not null default '{}'::jsonb,
  occurred_at timestamptz not null,
  received_at timestamptz not null default now(),
  legacy_signal_id integer,
  unique (project_id, legacy_signal_id)
);

create index signal_records_project_signal_idx
  on public.signal_records (project_id, signal, occurred_at desc);

alter table public.signal_records enable row level security;

create function private.is_project_member(p_project_id uuid, p_min_role text default 'viewer')
returns boolean
language sql
security definer
stable
set search_path = public
as $$
  select private.is_org_member(
    (select organization_id from public.projects where id = p_project_id),
    p_min_role
  );
$$;

grant execute on function private.is_project_member(uuid, text) to authenticated;
revoke execute on function private.is_project_member(uuid, text) from public, anon;

create policy "signal_records_select_member" on public.signal_records
  for select using (private.is_project_member(project_id, 'viewer'));

create policy "signal_records_insert_member" on public.signal_records
  for insert with check (private.is_project_member(project_id, 'member'));

create policy "signal_records_delete_admin" on public.signal_records
  for delete using (private.is_project_member(project_id, 'admin'));

-- No update policy: signal observations are append-only (Spec_Upgrade.md
-- section 8.2 - "Immutable event records should generally be append-only").
