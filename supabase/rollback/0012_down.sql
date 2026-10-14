drop index if exists public.connected_models_created_by_idx;
-- The revokes are not rolled back: restoring access for signed-in users to the runner's functions would only loosen security.
