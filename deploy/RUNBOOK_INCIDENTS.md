# Incident runbook

What to do when something goes wrong, in the order to do it. Each section has **the first two minutes** (stop the damage), then the
full steps, then what to tell users. Every SQL file referenced here is rehearsed on a scratch database in CI
(`scripts/test_switches_local.py`, `scripts/test_runbook_local.py`), so the commands are known to work.

Where things live: Supabase (database and auth), Vercel (website), Render (API and the free-allowance relay), GitHub (code, the
scheduled runner, releases), PyPI (the `driftwatch-llm` package).

## The kill switches

| To stop | Do this | Effect |
|---|---|---|
| Ingest of new scores | `supabase/runbooks/switches_off.sql`, line A | Agents keep their events on disk and retry later; nothing is lost |
| New CLI sign-ins | same file, line B | `driftwatch init` / `login` fail with a plain message |
| New API keys | same file, line C | Existing keys keep working |
| The free allowance (relay) | same file, line D, or Render: `DISABLE_FREE_PROXY=true` | `/v1/judge` answers "not available" |
| Cloud connect | `update private.runner_policy set enabled = false;` and GitHub variable `CLOUD_CONNECT` = `off` | The runner claims nothing |
| Everything at once | all of `switches_off.sql` + `cloud_connect_compromise.sql` | Read-only website, no writes |
| To switch back on | `supabase/runbooks/switches_on.sql` | Restores exactly the original rights |

## 1. A project API key leaked

**First two minutes:** the owner of the key opens the project's **API keys** page and revokes it (one click twice). If you cannot
reach them, revoke it yourself: `update public.project_api_keys set revoked_at = now() where prefix = '<first 13 characters of the key>';`.
A key can only send events to one project and can read nothing, so the damage is bounded to junk or noisy events.

**Full steps:** look at the project's recent scores for events you do not recognise (the console chart; `signal_records` in SQL);
delete the junk with `delete from public.signal_records where project_id = '<id>' and received_at > '<when it leaked>';`;
tell the user to run `driftwatch login` (new key) and `driftwatch agent rotate-key` on every machine.

## 2. Many keys leaked, or abuse you cannot narrow down

**First two minutes:** `supabase/runbooks/switches_off.sql` line A (ingest off), then `supabase/runbooks/revoke_all_api_keys.sql`
(every key revoked, and it prints `0`). Agents queue their events and park with "run `driftwatch login`".

**Full steps:** find the cause (who created the keys: `select created_by, count(*) from public.project_api_keys group by 1 order by 2 desc;`),
fix it, run `switches_on.sql` line A, then tell users (template below).

## 3. The database or Supabase credentials leaked (service key, database password, JWT secret)

**First two minutes (Supabase dashboard):** Project Settings -> Database -> **Reset database password**; Project Settings -> API ->
roll the **JWT secret** (this signs everyone out and invalidates the old service key) and the publishable key if you suspect it.
Then update what uses them: Vercel (`NEXT_PUBLIC_SUPABASE_ANON_KEY` and the Supabase URL if it changed), Render
(`SUPABASE_ANON_KEY`, `SUPABASE_JWT_SECRET`), GitHub environment `cloud-runner` (`SUPABASE_ANON_KEY`), and the CLI's pinned publishable
key in `driftwatch_llm/endpoints.py` (a new release; until then the CLI shows "DriftWatch rejected the request").

**Full steps:** check the audit log (`select * from public.audit_events order by occurred_at desc limit 200;`) and Supabase's own
logs for the time window; revoke all API keys if any chance they were read (`revoke_all_api_keys.sql`: the hashes are not reversible,
but the point is to be sure); notify users that they must sign in again.

## 4. The free-allowance relay is being abused

**First two minutes:** `DISABLE_FREE_PROXY=true` on Render (takes effect on the next deploy; the database switch in
`switches_off.sql` line D is instant). Check the day's use: `select * from private.usage_daily order by day desc limit 5;` and the
biggest users: `select user_id, used from private.usage_totals order by used desc limit 10;`.

**Full steps:** lower the caps without a deploy: `update private.quota_policies set per_user_cap = 10, global_daily_cap = 100 where name = 'free';`.
Rotate the relay's provider key (new Groq key on Render, revoke the old at Groq) and the relay secret (generate a long random value,
update `FREE_PROXY_RELAY_SECRET` on Render and the hash in `private.quota_policies.relay_secret_hash`).

## 5. Cloud connect: the runner secret or private key may have leaked

Follow `deploy/RUNBOOK_CLOUD_CONNECT.md`, section "INCIDENT". It stops everything, lists the affected users, deletes every stored key and
tells you how to restart with new keys.

## 6. A bad CLI release is on PyPI

**First two minutes:** on PyPI, open the release -> **Yank** it (yanked versions stay installable only when pinned exactly, so new
installs stop getting it). Tell users which version to use: `pip install "driftwatch-llm==<last good>"`.

**Full steps:** fix, bump the version (never reuse a number), tag `cli-vX.Y.Z`, approve the `pypi` deployment. Agents of the bad
version: `driftwatch agent stop` after upgrading, because an old agent keeps running until it exits (it lingers 30 seconds after the
last app stops).

## 7. A GitHub account or workflow was compromised

**First two minutes:** GitHub -> Settings -> Environments -> `cloud-runner` and `pypi`: delete the secrets and set the variable
`CLOUD_CONNECT` to `off`; revoke the account's sessions and personal tokens; on PyPI revoke the trusted publisher (Manage -> Publishing)
until you have checked `.github/workflows/release-cli.yml` for unexpected changes.

**Full steps:** review the last commits to `main` and `.github/workflows/` (`CODEOWNERS` lists what matters); rotate everything the
runner holds (Cloud connect runbook); re-add the trusted publisher.

## 8. Vercel, Render or Supabase is down

The website, the API and the database fail independently. **The local agent keeps working** (it needs none of them to measure; it queues
scores and sends them when the cloud returns). Check the provider's status page first. Render's free instance also sleeps: the first
request after a quiet period takes about a minute (the agent and the relay client wait and retry). Nothing to do unless it lasts more than
an hour; then post a short notice on the site.

## 9. The daily keep-alive failed

Supabase pauses a free project after 7 days without activity; the daily `supabase-keepalive` workflow prevents it. If it fails: open
the run, read the line, and if the project is paused click **Restore project** in the Supabase dashboard, then rerun the workflow.
It also reports the cloud runner's health (see the cloud connect runbook).

## User notice template (adapt)

> Subject: What happened and what to do
>
> On <date> we found <what, in one sentence>. We have <stopped it, and what we changed>. <Whether any data was exposed, honestly: scores
> only, or also keys.> Please <the exact steps: `driftwatch login`, revoke your provider key, ...>. We are sorry. If anything looks
> wrong, reply to this email.

## After every incident

Write down the timeline in `Docs/progress_log.md` (what, when, who noticed, how long to stop it), add a test that would have caught
it, and update this runbook with what was slow or unclear.
