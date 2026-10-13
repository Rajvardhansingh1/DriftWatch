# Cloud connect: setup, rotation and incident runbook

Cloud connect stores users' provider API keys, sealed so that only the scheduled runner can open them. This file is the
operator's guide: turning it on, rotating secrets, and what to do if something leaks. Everything that can be rehearsed
has been: `scripts/test_runbook_local.py` runs the SQL below on a scratch database and fails if it stops working.

## The pieces (and who can read what)

| Piece | Holds | Can open a user's key? |
|---|---|---|
| Vercel (website) | `CONNECT_PUBLIC_KEY`, `CONNECT_KEY_ID` (server only) | No: a public key can only seal |
| Supabase | the sealed key (`private.connected_secrets`), the **hash** of the runner secret | No |
| GitHub environment `cloud-runner` | `RUNNER_PRIVATE_KEY`(S), `RUNNER_SECRET`, `SUPABASE_URL`, `SUPABASE_ANON_KEY` | Yes, while a job runs |
| Render | nothing for this feature | No |

Two switches, both off until launch: the database (`private.runner_policy.enabled`) and the repository variable
`CLOUD_CONNECT` (`on`/anything else). The website also needs `cloudConnect` in `NEXT_PUBLIC_FEATURES`.

## First-time setup (once)

1. `python scripts/make_runner_keys.py` in a private terminal. It prints five values and saves nothing.
2. GitHub: Settings -> Environments -> New environment `cloud-runner`. **Deployment branches: only `main`.** Add secrets
   `RUNNER_PRIVATE_KEY`, `RUNNER_SECRET`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`. Do **not** add required reviewers: a
   scheduled run would wait for approval forever.
3. Vercel: `CONNECT_PUBLIC_KEY` and `CONNECT_KEY_ID` (server-side variables, **not** `NEXT_PUBLIC_`).
4. Supabase SQL editor: run the printed `update private.runner_policy set runner_secret_hash = ...` line, apply migration
   0011 first if you have not.
5. GitHub branch protection on `main`: require pull requests and **Require review from Code Owners** (`.github/CODEOWNERS`
   covers the workflows, `monitor/cloud/`, `supabase/`, the runner requirements and the connect code).
6. Go-live is a separate, deliberate step: `update private.runner_policy set enabled = true;`, repository variable
   `CLOUD_CONNECT` = `on`, then `cloudConnect` in `NEXT_PUBLIC_FEATURES` on Vercel and a redeploy.

## Health and the 60-day auto-disable

GitHub disables scheduled workflows in a public repository after 60 days without repository activity. The daily
`supabase-keepalive` workflow calls `runner_health()` and **fails (you get an email)** when a connected model is more than two
intervals late, or when decrypts outnumber claims in 24 hours (which would mean something other than the runner is opening keys).
If it fails because the schedule was disabled: Actions -> cloud-runner -> "Enable workflow", then run it once by hand.

## Drill A: rotate the runner key pair (do this once before launch, then yearly)

1. `python scripts/make_runner_keys.py --key-id 2`. Keep the output.
2. GitHub: add the new private key to the map secret **`RUNNER_PRIVATE_KEYS`** as JSON with both ids, for example
   `{"1": "<old private key>", "2": "<new private key>"}`. (The runner uses this map instead of `RUNNER_PRIVATE_KEY` when it is set.)
3. Vercel: set `CONNECT_PUBLIC_KEY` to the new public key and `CONNECT_KEY_ID` to `2`; redeploy. New connections now use key 2.
4. Old rows still open with key 1. Ask users to reconnect (or delete rows you cannot wait for). `runner_health()` shows
   `key_ids` (rows per key id). When `key_ids` has no `"1"`, remove key 1 from the map and the drill is done.
5. Record the date and the result in the progress log.

## Drill B: rotate the runner secret

1. `python scripts/make_runner_keys.py` and keep **only** `RUNNER_SECRET` and the SQL line (discard the key pair).
2. Run the SQL line in Supabase first, then update the GitHub secret `RUNNER_SECRET`. Between the two steps one run fails safely
   ("the database refused"): that is the expected cost of rotating.

## Drill C: a user rotates their own provider key

On the connect page: Replace. The old sealed key is deleted with its row. (They should also revoke the old key at their provider.)

## INCIDENT: the runner secret or private key may have leaked

Do these in order. The first two take under two minutes and stop all access.

1. **Supabase SQL editor**: run `supabase/runbooks/cloud_connect_compromise.sql` top to bottom. It switches the feature off,
   removes the runner secret hash (every runner function now refuses), lists the affected users (step 2: **copy that result
   before step 3 deletes the rows**), deletes every stored key, and checks the counts are zero.
2. **GitHub**: set the repository variable `CLOUD_CONNECT` to `off`; disable the `cloud-runner` workflow; delete the
   environment secrets `RUNNER_PRIVATE_KEY(S)` and `RUNNER_SECRET`.
3. **Vercel**: remove `CONNECT_PUBLIC_KEY` (the connect page then refuses to seal) and take `cloudConnect` out of
   `NEXT_PUBLIC_FEATURES`; redeploy.
4. **Tell the users** from the step 2 list, using the template below. Their keys were deleted from DriftWatch, but the safe
   assumption is that a leaked private key plus a database copy could open them, so they must revoke them at the provider.
5. **Find the cause** (workflow run history, the environment's deployment log, recent pushes to `main`, the audit
   rows: `select * from private.runner_audit order by at desc limit 200;`), fix it, then redo first-time setup with
   **new** keys and a new runner secret. Re-enable only after a `security-review` of what happened.

User notice template:

> Subject: Please revoke your provider API key
>
> DriftWatch's cloud runner secrets may have been exposed on <date>. We have switched the feature off and deleted every API
> key you stored with us. As a precaution, please revoke the key you connected (<provider>, ending in <last4>) in your provider's
> dashboard and create a new one before you connect again. We have no evidence your key was used, and the only thing the
> runner could do with it was send short fixed questions to your provider on your schedule. We are sorry. What happened and
> what we changed: <link>.

## Limits (honest)

- A sealed key is safe only while the private key stays secret. The private key lives in a GitHub environment secret that
  only workflows on `main` can read, so anyone who can change what runs on `main` can read users' keys. That is why
  `CODEOWNERS`, branch protection and the pinned, audited runner dependencies are part of this feature, not extras.
- The audit trail records that a decrypt happened, never what was decrypted.
- Nothing here protects a user whose provider key has no spend limit. The connect page says so; setting a limit at the
  provider is the user's best defence.
