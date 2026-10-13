drop function if exists public.my_quota();
drop function if exists public.settle_quota(text, uuid, text, text);
drop function if exists public.reserve_quota(text, uuid, text);
drop function if exists private.quota_key_owner(text);
drop function if exists private.require_relay(text);
drop table if exists private.usage_ledger;
drop table if exists private.usage_daily;
drop table if exists private.usage_totals;
drop table if exists private.quota_policies;
