# Launch gates: hardening evidence

Generated from `deploy/hardening_matrix.json` by `scripts/make_launch_gates.py`; do not edit by hand.
`tests/test_launch_gates.py` checks that every referenced test or file exists.

52 items: 46 tested, 4 by design, 2 need an owner action.

| ID | Risk | Status | Evidence | Owner action |
|---|---|---|---|---|
| A1 | SECURITY DEFINER helpers executable by anon | tested | `tests/test_repo_hygiene.py::test_only_allowlisted_functions_are_executable_by_anon`<br>`tests/test_migrations_static.py::test_0005_revokes_anon_on_known_definer_functions`<br>`supabase/migrations/0012_runner_privileges.sql` |  |
| A2 | create_organization executable by anon | tested | `tests/test_repo_hygiene.py::test_only_allowlisted_functions_are_executable_by_anon`<br>`supabase/tests/0001_cross_tenant_isolation.sql` |  |
| A3 | audit_events had no write path | tested | `supabase/tests/0002_api_keys_ingest.sql`<br>`supabase/tests/0006_connected_models.sql` |  |
| A4 | RLS policies call auth.uid() per row | tested | `tests/test_migrations_static.py::test_0006_definer_functions_pin_empty_search_path`<br>`supabase/migrations/0005_security_hardening.sql` |  |
| A5 | No security headers or middleware | tested | `frontend/tests/headers.test.ts`<br>`frontend/tests/middleware.test.ts` |  |
| A6 | validate_event unbounded timestamps, meta and values | tested | `tests/test_cloud_ingest.py::test_future_timestamp_rejected`<br>`tests/test_cloud_ingest.py::test_ancient_timestamp_rejected`<br>`tests/test_cloud_ingest.py::test_meta_too_many_keys_rejected`<br>`tests/test_cloud_ingest.py::test_absurd_value_rejected` |  |
| A7 | signal_records insert path set protected columns (direct inserts now closed) | tested | `supabase/tests/0002_api_keys_ingest.sql`<br>`supabase/tests/0003_console_functions.sql`<br>`supabase/tests/0007_remaining_surface.sql`<br>`supabase/migrations/0013_least_privilege.sql` |  |
| A8 | JWT verification (legacy HS256 only) | tested | `tests/test_cloud_auth.py::test_es256_token_verified_through_jwks`<br>`tests/test_cloud_auth.py::test_alg_none_token_is_rejected`<br>`tests/test_cloud_auth.py::test_wrong_secret_raises_auth_error` |  |
| A9 | .mcp.json tracked in git | tested | `tests/test_repo_hygiene.py::test_mcp_json_is_not_tracked` |  |
| A10 | Secret scan | tested | `tests/test_repo_hygiene.py::test_dotenv_is_not_tracked`<br>`.gitleaks.toml`<br>`.github/workflows/ci.yml` |  |
| B1 | Sign-up abuse farming the free quota | tested | `supabase/tests/0005_usage_quota.sql`<br>`supabase/tests/0006_connected_models.sql` | Supabase Auth: email confirmation on (see supabase/AUTH_SETTINGS.md) |
| B2 | Credential stuffing and weak passwords | owner action | `supabase/AUTH_SETTINGS.md` | Supabase Auth: minimum password length 10 and leaked-password protection |
| B3 | Open redirect | tested | `frontend/tests/safe-redirect.test.ts` | Supabase redirect allow-list holds exact URLs only |
| B4 | Account enumeration | owner action | `supabase/AUTH_SETTINGS.md` | Confirm sign-in and reset answer identically for known and unknown emails (smoke test) |
| B5 | Logout leaves the refresh token valid | tested | `frontend/tests/console-pages.test.ts`<br>`tests/cli/test_cli.py::test_logout_revokes_on_the_server_then_deletes_locally` |  |
| B6 | Demo is a shared mutable relay | tested | `tests/test_rate_limit.py`<br>`tests/test_main_api.py`<br>`tests/test_force_simulated.py` |  |
| B7 | Landing page claims the product cannot back | tested | `frontend/tests/content.test.ts`<br>`frontend/tests/legal-connect.test.ts` |  |
| B8 | Third-party scripts widen XSS and privacy exposure | tested | `frontend/tests/headers.test.ts`<br>`frontend/tests/middleware.test.ts` |  |
| B9 | Legal pages | tested | `frontend/tests/legal.test.ts` | Owner reads privacy, terms and data-deletion pages before launch |
| C1 | Repo-controlled config exfiltration | tested | `tests/cli/test_project.py::test_hostile_config_cannot_set_endpoints_or_keys`<br>`tests/cli/test_cli.py::test_init_in_a_cloned_untrusted_repo_refuses_and_contacts_nobody`<br>`tests/capture/test_autostart.py::test_an_untrusted_folder_starts_nothing_sends_nothing_and_says_so_once_a_day` |  |
| C2 | Fork bomb and recursion | tested | `tests/agent/test_launcher.py::test_fifty_simultaneous_starters_leave_exactly_one_agent`<br>`tests/agent/test_launcher.py::test_the_spawned_agent_runs_with_capture_disabled` |  |
| C3 | Feedback loop: the agent captures its own judge calls | tested | `tests/agent/test_launcher.py::test_the_spawned_agent_runs_with_capture_disabled`<br>`tests/capture/test_wrappers.py` |  |
| C4 | Startup race and deadlock | tested | `tests/agent/test_launcher.py::test_a_hard_killed_agent_is_replaced`<br>`tests/agent/test_launcher.py::test_a_spawn_that_loses_the_lock_to_an_agent_still_shutting_down_is_retried_not_recorded_as_a_failure`<br>`tests/agent/test_lock.py` |  |
| C5 | Localhost API attackable from any website | tested | `tests/agent/test_dashboard.py::test_a_foreign_host_header_is_refused_even_with_a_valid_cookie`<br>`tests/agent/test_dashboard.py::test_a_foreign_origin_is_refused_and_there_are_no_cors_headers`<br>`tests/agent/test_ipc.py` |  |
| C6 | Secrets at rest without a keychain | tested | `tests/cli/test_secrets.py`<br>`tests/cli/test_providerkeys.py`<br>`tests/cli/test_canary_keys.py` |  |
| C7 | Device-code flow attacks | tested | `supabase/tests/0004_device_auth.sql`<br>`tests/cli/test_device_flow.py` |  |
| C8 | Capture breaks or slows the user's app | tested | `tests/capture/test_wrappers.py`<br>`tests/capture/test_client.py`<br>`tests/capture/test_real_sdks.py` |  |
| C9 | Privacy: prompts and responses are sensitive | tested | `tests/agent/test_engine.py::test_no_response_text_reaches_the_store_the_outbox_or_disk`<br>`tests/test_agent_testkit.py::test_the_kit_passes_end_to_end`<br>`tests/core/test_redact.py` |  |
| C10 | Judge prompt injection | tested | `tests/test_llm_proxy.py::test_an_answer_that_is_not_just_a_number_from_0_to_10_is_a_failure_and_a_refund`<br>`tests/test_llm_proxy.py::test_a_response_cannot_close_the_quoted_block_and_smuggle_instructions` |  |
| C11 | Outbox misbehaviour: storms, growth, revoked key loops | tested | `tests/agent/test_sync.py::test_a_revoked_key_parks_the_project_without_losing_events_then_a_new_key_resumes`<br>`tests/agent/test_sync.py::test_server_errors_back_off_and_stop_the_round`<br>`tests/agent/test_store.py`<br>`tests/test_agent_testkit.py::test_offline_then_online_delivers_everything_once` |  |
| C12 | Supply chain: name, release, install-time code | tested | `tests/test_release_workflow.py::test_publish_uses_a_sha_pinned_action_from_the_pypi_environment_with_no_token`<br>`tests/cli/test_package.py` |  |
| C13 | Several API keys per project | tested | `supabase/tests/0002_api_keys_ingest.sql` |  |
| C14 | Lost laptop or leaked key: keys are write-only | tested | `supabase/tests/0002_api_keys_ingest.sql`<br>`supabase/runbooks/revoke_all_api_keys.sql` |  |
| D1 | Ingest goes straight to Supabase, not Render | tested | `tests/cli/test_api_ingest.py`<br>`supabase/tests/0002_api_keys_ingest.sql` |  |
| D2 | RPC hardening: definer, empty search_path, revoked from public | tested | `tests/test_repo_hygiene.py::test_new_definer_functions_pin_empty_search_path`<br>`tests/test_migrations_static.py::test_0006_definer_functions_pin_empty_search_path` |  |
| D3 | No god key for the runner | by design | `supabase/tests/0006_connected_models.sql`<br>`supabase/migrations/0011_connected_models.sql`<br>`deploy/RUNBOOK_CLOUD_CONNECT.md`<br>The runner holds no database login at all: it calls definer functions through the public API with a runner secret, and nothing else. |  |
| D4 | Free project pauses after 7 days of inactivity | by design | `.github/workflows/supabase-keepalive.yml`<br>`tests/test_migrations_static.py::test_0007_has_retention_realtime_and_ping` |  |
| D5 | Unbounded signal_records growth | tested | `tests/test_migrations_static.py::test_0007_has_retention_realtime_and_ping`<br>`tests/test_migrations_static.py::test_0007_indexes_occurred_at_for_nightly_prune` |  |
| D6 | Realtime load and RLS cost | tested | `frontend/tests/console-lib.test.ts`<br>`frontend/tests/middleware.test.ts` |  |
| D7 | Deletion and export | tested | `supabase/tests/0003_console_functions.sql`<br>`supabase/tests/0006_connected_models.sql` |  |
| D8 | Audit trail | tested | `supabase/tests/0002_api_keys_ingest.sql`<br>`supabase/tests/0006_connected_models.sql` |  |
| E1 | Free proxy as an open LLM relay | tested | `tests/test_llm_proxy.py::test_the_caller_cannot_choose_the_prompt_model_or_destination`<br>`tests/test_llm_proxy.py::test_a_replayed_idempotency_key_is_409_and_does_not_call_the_provider_again` |  |
| E2 | Quota race and double spend | tested | `supabase/tests/0005_usage_quota.sql`<br>`scripts/test_quota_concurrency_local.py` |  |
| E3 | Runaway total spend | tested | `tests/test_llm_proxy.py::test_the_kill_switch_and_a_missing_provider_close_the_route`<br>`supabase/tests/0005_usage_quota.sql`<br>`supabase/runbooks/switches_off.sql` |  |
| E4 | BYOK SSRF and key exfiltration | tested | `tests/test_providers.py::test_an_unknown_provider_or_a_host_override_is_refused_before_any_request`<br>`frontend/tests/connect-core.test.ts`<br>`supabase/tests/0006_connected_models.sql` |  |
| E5 | Key leakage through logs and exceptions | tested | `tests/test_llm_proxy.py::test_request_text_keys_and_provider_words_never_reach_any_log_line`<br>`tests/test_runner.py::test_no_key_answer_or_private_key_reaches_stdout_stderr_or_logs`<br>`tests/test_logging_redaction.py::test_project_api_keys_are_redacted`<br>`tests/cli/test_canary_keys.py` |  |
| E6 | Stored-key blast radius | tested | `tests/test_seal.py::test_a_sealed_key_cannot_be_moved_altered_or_opened_by_anyone_else`<br>`scripts/test_runner_e2e_local.py`<br>`deploy/RUNBOOK_CLOUD_CONNECT.md` | Rotation drills and the compromise tabletop (cloud-connect runbook, Parts 3 and 4) |
| E7 | Cloud runner cost and abuse | tested | `supabase/tests/0006_connected_models.sql`<br>`tests/test_providers.py` |  |
| F1 | Two runners run the same job | tested | `scripts/test_runner_concurrency_local.py`<br>`supabase/tests/0006_connected_models.sql` |  |
| F2 | Runner dies mid-job, lease never freed | tested | `supabase/tests/0006_connected_models.sql` |  |
| F3 | Free hosting sleeps and has an ephemeral disk | by design | `.github/workflows/cloud-runner.yml`<br>`tests/test_workflows.py::test_the_runner_only_runs_on_a_schedule_or_by_hand_never_from_a_pull_request`<br>The runner is a scheduled workflow that keeps no local state; vectors and jobs live in the database. |  |
| F4 | Quota and ingest contend on hot rows | by design | `supabase/migrations/0010_usage_quota.sql`<br>`supabase/migrations/0006_api_keys_ingest.sql`<br>Ingest does not touch the quota rows; the lock order is documented in both migrations. |  |

## Residual risks (cannot be designed away)

- A compromised user machine can read its own keychain and local data. We limit what the cloud can leak.
- Cloud-connect keys are decryptable by the runner by definition. They are sealed so that only the runner can open them; see `deploy/RUNBOOK_CLOUD_CONNECT.md`. Users who cannot accept this use the local agent with their own key.
- A malicious dependency in a user's own environment can already read their process. The `.pth` hook adds no new privilege and is visible and removable.
- Provider outages and SDK changes will break capture for some versions; the design makes this fail safe, not never.
