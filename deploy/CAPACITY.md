# Capacity: what runs out first on the free plans, and what to do

Written 2026-10-14 from the live project (13 MB database, 30 score rows, 1 user). Free-plan limits change; check each provider's pricing
page before relying on a number here.

## Supabase (database, auth, realtime)

| Limit (free plan, as last checked) | What uses it | How we keep it small |
|---|---|---|
| Database 500 MB, read-only when full | `signal_records` is the only table that grows | Raw rows are kept 30 days, then rolled into hourly summaries (`signal_hourly`, one row per project, signal and hour); `runner_audit` keeps 90 days |
| 7 days idle pauses the project | nothing in particular | The daily `supabase-keepalive` workflow pings it |
| Realtime connections and messages | one subscription per open project page | One channel per project; the `Offline` chip shows when it is not connected |
| Egress and API requests | the website's reads, agents' ingest calls | Agents send one small event about every minute while an app runs; the console limits points per chart to 500 |

**Rough sizing.** One score row is well under 1 KB with its indexes. An agent that is busy all day emits about 2,900 rows a day
(two signals roughly once a minute), so 30 days is about 87,000 rows, around 50 MB. Ten such projects fill the free database. The
hourly summaries are tiny (about 24 rows a day per project and signal), so they do not matter.

**The alarm.** `scripts/capacity_check.py` runs daily in the keep-alive workflow and fails (you get an email) above **70%** of 500 MB. It reads
`ops_report`, which returns sizes and counts only. It needs the runner secret in the `cloud-runner` environment; without it the step says it
is skipped.

**At 70%, in this order:**
1. Shorten raw retention. In SQL, change the prune window in `private.rollup_and_prune` (30 days) to 14: new migration, not an edit.
2. Look for one project dominating: `select project_id, count(*) from public.signal_records group by 1 order by 2 desc limit 5;`. A runaway
   agent is a bug to fix (and `switches_off.sql` line A stops ingest while you do).
3. Upgrade the Supabase plan (a monthly cost; the owner decides). Pausing the free project is **not** an option once real users depend on it.

## Render (the API and the free-allowance relay)

Free web service: sleeps after 15 minutes idle, wakes in about a minute, 512 MB memory. The relay tolerates the wake-up (the agent waits
and retries). The demo and relay share the instance, so heavy demo use slows the relay. If the relay becomes important, move it to a paid
instance (it is stateless).

## Vercel (the website)

Free (hobby) plan limits on bandwidth and function invocations are far above anything the site does today. The dashboard pages are
server-rendered per request; watch the usage page after launch.

## GitHub Actions (the cloud runner, CI)

Public repository: Actions minutes are free. The runner uses about one minute per run, 96 runs a day. Scheduled workflows are disabled
after 60 days without repository activity (the keep-alive workflow alarms on a stale runner).

## PyPI

Free. A release can be yanked but not replaced; never reuse a version number.
