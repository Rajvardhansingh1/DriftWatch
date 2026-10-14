-- RUNBOOK: the cloud runner's secret or private key may have leaked (or any stored-key incident).
-- Run in the Supabase SQL editor as the project owner, top to bottom. Rehearsed on a scratch Postgres by
-- scripts/test_runbook_local.py, which fails if this file stops doing what it says.
-- The GitHub, Vercel and user-notification steps are in deploy/RUNBOOK_CLOUD_CONNECT.md. Do those too.

-- 1. STOP. Nothing can be claimed, opened or connected after this statement: the runner secret hash is gone, so every
--    runner function refuses, and the switch is off, so connect_model refuses.
update private.runner_policy set enabled = false, runner_secret_hash = null;

-- 2. WHO TO TELL, before the rows are deleted: one row per affected project (copy this result somewhere safe).
select p.name as project, u.email, m.provider, m.model, m.last4 as key_ends_with
from public.connected_models m
join public.projects p on p.id = m.project_id
join auth.users u on u.id = m.created_by
order by u.email;

-- 3. DELETE every stored key (cascades to the sealed secrets, jobs and reference vectors).
delete from public.connected_models;

-- 4. CHECK. All three counts must be 0 / false.
select (select count(*) from private.connected_secrets) as secrets_left,
       (select count(*) from private.connected_jobs) as jobs_left,
       (select enabled from private.runner_policy) as switch_on;
