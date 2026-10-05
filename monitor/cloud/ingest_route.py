"""POST /v1/events - authenticated, validated, idempotent event ingestion
(schemas/API_CONTRACT.md). Identity comes from the bearer token; project
authorization comes from RLS in the cloud store, not from this code."""
from __future__ import annotations

from typing import Protocol
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query

from monitor.cloud.auth import AuthError, verify_access_token
from monitor.cloud.ingest import IngestionError, validate_event
from monitor.cloud.supabase_store import SupabaseStoreError


class EventSink(Protocol):
    def insert(self, access_token: str, project_id: str, event) -> str: ...


def build_router(sink: EventSink) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["ingestion"])

    @router.post("/events", status_code=202)
    def ingest(
        payload: dict,
        project_id: str = Query(...),
        authorization: str | None = Header(default=None),
    ):
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="missing bearer token")
        token = authorization.removeprefix("Bearer ").strip()
        try:
            verify_access_token(token)
        except AuthError:
            raise HTTPException(status_code=401, detail="invalid or expired token")

        try:
            UUID(project_id)
        except ValueError:
            raise HTTPException(status_code=422, detail="project_id must be a UUID")

        try:
            event = validate_event(payload)
        except IngestionError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

        try:
            outcome = sink.insert(token, project_id, event)
        except SupabaseStoreError:
            raise HTTPException(status_code=503, detail="cloud store unavailable, retry later")

        if outcome == "forbidden":
            raise HTTPException(status_code=403, detail="not a member of this project")
        return {"status": outcome, "event_id": event.event_id}

    return router
