-- Idempotent ingestion key + append-only audit trail.
-- event_id is the client-assigned UUID from schemas/event.v1.json. The unique
-- constraint is the atomic idempotency guard: a retried POST /v1/events for the
-- same (project_id, event_id) hits 23505 and is reported as a duplicate.

alter table public.signal_records add column event_id uuid;
alter table public.signal_records add constraint signal_records_project_event_unique
  unique (project_id, event_id);

-- Platform-operator audit trail (Spec_Upgrade.md 13.3). Written only by the
-- server with a restricted role. No client policies are created, so RLS
-- denies every direct client read and write.
create table public.audit_events (
  id uuid primary key default gen_random_uuid(),
  actor_user_id uuid,
  action text not null,
  result text not null check (result in ('ok', 'denied', 'error')),
  occurred_at timestamptz not null default now()
);

alter table public.audit_events enable row level security;
revoke all on public.audit_events from anon, authenticated;
