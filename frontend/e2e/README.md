# Console browser check (dev only)

Production sign-in needs a CAPTCHA, so the signed-in console cannot be driven in a browser
against the real project. This folder holds a local stand-in:

- `fake-supabase.mjs`: a tiny HTTP server on `http://127.0.0.1:54321` that answers the Auth
  and PostgREST calls the console makes (`/auth/v1/user`, `/auth/v1/logout`, the refresh-token
  grant, `GET /rest/v1/{projects,signal_records,signal_hourly,project_api_keys}` with `eq`/`gte`
  filters, `order`, `limit` and single-object requests, and the RPCs `create_project`,
  `create_project_api_key`, `revoke_project_api_key`, `export_my_data`, `delete_my_account`).
  State is in memory and reset on every start. One user (`tester@example.com`, bearer
  `fake-token`) and one seeded project, "Demo app". Realtime is not implemented.
- `run.mjs`: builds the app against the fake, starts `next start -p 3100` and the fake, sets the
  `@supabase/ssr` session cookie (`sb-127-auth-token`, `base64-` + base64url JSON), drives
  headless Chrome through the console and prints a PASS/FAIL table. Both servers are stopped
  at the end, also on failure. Exit code is non-zero if any check fails.

Nothing here is imported by `app/`, `lib/` or `components/` (`tests/console-e2e-files.test.ts`
enforces this) and nothing here is deployed.

## Run

```bash
# once, outside the repo: playwright-core is not a project dependency
mkdir C:/tmp/pw && cd C:/tmp/pw && npm init -y && npm i playwright-core

cd frontend
PLAYWRIGHT_CORE_DIR=C:/tmp/pw node e2e/run.mjs
```

- `PLAYWRIGHT_CORE_DIR`: folder whose `node_modules` contains `playwright-core`. Defaults to
  the scratchpad folder used when the harness was written
  (`C:/Users/RAJVAE~1/AppData/Local/Temp/claude/.../scratchpad/live`).
- `CHROME_PATH`: Chrome binary, default `C:/Program Files/Google/Chrome/Application/chrome.exe`.
- `E2E_SKIP_BUILD=1`: reuse the existing `.next` (must already be built by `run.mjs`).
- `E2E_VERBOSE=1`: log every request the fake receives and the Next server output.

Screenshots go to `.superpowers/sdd/2026-10-07-plan-2-cloud-console/shots/` (git-ignored).

`run.mjs` leaves `.next` built against the fake; run `npm run build` again before using it for
anything else.

## What this cannot verify

Realtime delivery, real row-level security, the real SQL in the RPCs (limits, audit rows,
cascades), email confirmation, CAPTCHA and the real cookie refresh path. Those need the
real project.
