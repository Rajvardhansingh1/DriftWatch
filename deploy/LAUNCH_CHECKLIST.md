# Launch checklist (owner)

Everything the code can prove is in `deploy/LAUNCH_GATES.md`. This is what only the owner can do, in order. Tick each box; nothing
here needs a code change unless a step says so.

## 1. Apply the pending database migrations (Supabase SQL Editor)

Run each file's contents, one at a time, then re-run the verification line.

- [ ] `supabase/migrations/0013_least_privilege.sql`. Verify: `select has_table_privilege('anon','public.profiles','select');` returns `false`.
- [ ] `supabase/migrations/0014_ops_report.sql`. Verify: the daily `capacity` job in `supabase-keepalive` goes green (run it by hand once).
- [ ] Supabase dashboard -> Advisors: compare with `deploy/ADVISOR_NOTES.md`; anything not listed there is new.
- [ ] Authentication -> Password security: **Prevent use of leaked passwords** on, minimum length 10 (`supabase/AUTH_SETTINGS.md`).

Rollbacks exist in `supabase/rollback/` if a step misbehaves.

## 2. Merge and release

- [ ] Merge `fix/judge-scenario-wait` if it is still open (the judge scenario wait fix).
- [ ] Merge the Plan 9 PR (CI green: backend, agent-tests, frontend, sql, audit-runner, secrets).
- [ ] Tag `cli-v0.5.0`, approve the `pypi` deployment. The release now also attaches `sbom` (CycloneDX) and a signed build provenance
      attestation. Check: `gh attestation verify <downloaded wheel> --repo Rajvardhansingh1/DriftWatch`.
- [ ] Render redeploys on merge; the old `/v1/events` route is gone (agents use Supabase directly). Check `GET /health`.

## 3. Review packet for an independent reviewer (gate J8)

Hand someone who has not seen the code: `deploy/REVIEW_PACKET.md`, plus read access to the repository. Ask for written findings; fix or
record each in `deploy/ADVISOR_NOTES.md`. Optional but strongly advised before inviting strangers.

- [ ] Reviewer chosen. [ ] Findings received. [ ] Each fixed or accepted with a reason.

## 4. Product decisions

- [ ] Read the privacy, terms and data-deletion pages as a user would (`/legal/*`); fix wording that overpromises.
- [ ] **Domain.** The CLI pins the website address in `driftwatch_llm/endpoints.py`. Changing from the `vercel.app` address later means a
      CLI release and a window where old CLIs point at the old address, so decide before 1.0.
- [ ] Final `NEXT_PUBLIC_FEATURES` on Vercel (leave `cloudConnect` off until step 6).

## 5. Human smoke tests (browser)

Plans 2 and 3 are only half-verified (`scripts/smoke_production.py` covers the automatable half):

- [ ] Sign up, confirm email, sign in, sign out; a wrong password and an unknown email give the same message.
- [ ] Create a project, create a key, send an event with curl, see it on the chart, revoke the key and see the next curl rejected.
- [ ] Export the project, delete the project, delete the account.
- [ ] `pip install -U "driftwatch-llm[agent]"`, `driftwatch init` (approve in the browser), run an app, `driftwatch agent status`.

## 6. Cloud connect (after all development plans are done)

- [ ] `deploy/RUNBOOK_CLOUD_CONNECT.md` Part 3 (drills) and Part 4 (incident tabletop).
- [ ] Then, and only then: runner policy on, `CLOUD_CONNECT` variable on, `cloudConnect` in `NEXT_PUBLIC_FEATURES`. Rollback is
      `switches_off.sql` plus the same three in reverse.

## 7. Code review and go-live

- [ ] `/code-review ultra` on the final branch (user-triggered, billed); fix what it finds.
- [ ] Lighthouse on the production home page after the deploy: performance and SEO >= 90, accessibility >= 95.
      (Measured 2026-10-14 before the hero change: performance 89, accessibility 100, best practices 100, SEO 100.)
- [ ] Keep `supabase/runbooks/switches_off.sql` and `deploy/RUNBOOK_INCIDENTS.md` somewhere you can open from a phone.
