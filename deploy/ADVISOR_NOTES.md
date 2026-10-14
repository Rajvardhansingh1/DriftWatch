# Supabase advisors: what is accepted and why

Gate J2 reads "zero WARN or ERROR". The advisor can reach exactly zero only for a project that exposes no database functions to the API.
DriftWatch exposes a fixed set on purpose, because the agent, the CLI, the website and the relay call them through the public API with no
server of ours in between. This file is the written record of what remains, so a new finding stands out.

Last run: 2026-10-14 (before migrations 0012 and 0013 were applied there: see "Findings fixed" below).

## Accepted, by design

| Advisor | Count | Why it stays |
|---|---|---|
| `anon_security_definer_function_executable` | 13 | The allow-listed functions that need no sign-in: `ingest_event`, `start_device_login`, `poll_device_login`, `revoke_api_key_by_secret`, `reserve_quota`, `settle_quota`, and the seven `runner_*` functions. Each authenticates a secret itself (a project key, a device code or the runner secret) and fails closed. The list is enforced by `tests/test_repo_hygiene.py::test_only_allowlisted_functions_are_executable_by_anon`; adding one needs a reviewer. After migration `0012` only these 13 remain. |
| `authenticated_security_definer_function_executable` | the website's RPCs | `create_project`, `create_project_api_key`, `revoke_project_api_key`, `delete_my_account`, `connect_model`, `set_probes`, `update_connected_model`, `delete_connected_model`, `my_quota`, the device approval functions and `create_organization`: each checks `auth.uid()` and the caller's role inside. Writes by signed-in users go only through these. |
| `rls_enabled_no_policy` (INFO) | the `private` tables | Intentional: row-level security on with **no policy** means no client role can read or write them at all. Only the definer functions can. |
| `unused_index` (INFO) | 2 | Indexes on tables that have no traffic yet (the runner is off); they matter once it runs. |

## Owner action (cannot be set from code)

| Advisor | What to do |
|---|---|
| `auth_leaked_password_protection` | Supabase dashboard -> Authentication -> Sign In / Providers -> Email (or Password security): turn on **Prevent use of leaked passwords**. Also confirm minimum password length 10 (B2). |

## Findings fixed by the launch-gate review

- **0012:** the seven `runner_*` functions were executable by `authenticated` (Supabase's default grant); revoked. Added the missing index on
  `connected_models.created_by`.
- **0013:** `anon` held every table privilege (TRUNCATE included) on `profiles`, `organizations` and `organization_members`; signed-in users
  held write and TRUNCATE rights on read-only tables; members could insert into `signal_records` directly, bypassing `ingest_event`'s limits.
  Privileges now equal what the policies grant, the schema denies new tables and functions by default, and direct inserts are closed.
  The privilege audit in `supabase/tests/0007_remaining_surface.sql` fails if any table regains broad rights.

## How to re-run

Supabase dashboard -> Advisors -> Security and Performance, or ask the assistant to run `get_advisors`. Compare with the tables above; anything
not listed is new and needs a decision (fix it, or add it here with a reason).
