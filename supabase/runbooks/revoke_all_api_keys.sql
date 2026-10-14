-- Revokes EVERY project API key at once (a key leak you cannot narrow down). Users sign in again with `driftwatch login`
-- (or `driftwatch agent rotate-key`) to get a new key. Run switches_off.sql line A first if keys are being abused right now.
update public.project_api_keys set revoked_at = now() where revoked_at is null;

-- Check: must return 0.
select count(*) as active_keys_left from public.project_api_keys where revoked_at is null;
