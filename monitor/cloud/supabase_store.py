"""Cloud event sink: inserts one validated event into Supabase signal_records
through PostgREST, using the caller's own access token so RLS enforces
project membership. The unique (project_id, event_id) constraint from
migration 0004 is the atomic idempotency guard - a duplicate returns 409 and
is reported as 'duplicate', never double-counted.

Not exercised against a live project in this environment: see
tests/test_supabase_store.py (httpx MockTransport) and the Phase 2 note on
blocked live writes."""
from __future__ import annotations

import httpx

from monitor.cloud.ingest import ValidatedEvent


class SupabaseStoreError(Exception):
    """Transient or unexpected upstream failure. Route maps to 503, not 500."""


class SupabaseSignalStore:
    def __init__(self, base_url: str, anon_key: str, transport: httpx.BaseTransport | None = None):
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"apikey": anon_key},
            timeout=10.0,
            transport=transport,
        )

    def insert(self, access_token: str, project_id: str, event: ValidatedEvent) -> str:
        body = {
            "project_id": project_id,
            "event_id": event.event_id,
            "signal": event.signal,
            "value": event.value,
            "meta": {**event.meta, "source": event.source},
            "occurred_at": event.occurred_at.isoformat(),
        }
        try:
            resp = self._client.post(
                "/rest/v1/signal_records",
                json=body,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Prefer": "return=minimal",
                },
            )
        except httpx.HTTPError as exc:
            raise SupabaseStoreError("cloud store unreachable") from exc

        if resp.status_code == 201:
            return "accepted"
        if resp.status_code == 409:
            return "duplicate"
        if resp.status_code in (401, 403):
            return "forbidden"
        raise SupabaseStoreError(f"cloud store returned {resp.status_code}")
