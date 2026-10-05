# DriftWatch HTTP API contract

Machine-readable event schema: `schemas/event.v1.json`. This file describes the HTTP surface. Versioning follows the event schema: additive changes keep `schema_version` 1; breaking changes bump it.

## Liveness and readiness

| Method | Path | Auth | Responses |
|---|---|---|---|
| GET | `/api/health` | none | 200 `{status, embedding_drift_active}` (liveness) |
| GET | `/api/ready` | none | 200 `{status: "ready"}`; 503 `{detail: "database unavailable"}` (no internal detail) |

## Admin (platform operators only)

| Method | Path | Auth | Responses |
|---|---|---|---|
| GET | `/api/admin/status` | `Authorization: Bearer <Supabase access token>` | 200 `{status, scope}`; 401 missing/invalid/expired token; 403 authenticated but not on `PLATFORM_ADMIN_USER_IDS` |

Platform-admin status is an explicit configuration allowlist. It is never derived from email domain, user metadata, or organization role.

## Local demo (unchanged V1 routes)

`/api/query`, `/api/signals`, `/api/score`, `/api/scenario/*`, `/api/quota` keep their V1 behavior. They are demo/local routes and are not cloud-authenticated.

## Ingestion contract (library, HTTP route not yet exposed)

`monitor/cloud/ingest.py::validate_event` and `ingest_event` implement the contract:

- Unknown fields are rejected, not silently kept.
- `event_id` must be a UUID. `occurred_at` must be ISO-8601 with a timezone offset.
- `signal` must be one of the six published signal names.
- `value` must be a finite number (booleans rejected).
- `meta` is capped at 4096 bytes serialized.
- `content_capture` defaults to `false`.
- A repeated `(project_id, event_id)` returns `duplicate` and does not re-count.

An HTTP `POST /v1/events` route is NOT exposed yet. It needs a durable idempotency store (Supabase `signal_records` unique constraint), which is blocked by the pending Supabase permission path.

## Error model

Client contract violations return 4xx with a short, safe message. Internal faults return 5xx with no stack trace, SQL text, or key material.
