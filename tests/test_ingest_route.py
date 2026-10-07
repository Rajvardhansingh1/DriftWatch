import json
import time
import uuid
from datetime import datetime, timezone

import httpx
import jwt
import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from monitor.cloud.ingest_route import build_router
from monitor.cloud.supabase_store import SupabaseSignalStore, SupabaseStoreError
from monitor.config import settings

SECRET = "test-jwt-secret-do-not-use-in-production-0123456789"
PROJECT = "11111111-1111-1111-1111-111111111111"


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setattr(settings, "supabase_jwt_secret", SECRET)


def bearer():
    tok = jwt.encode(
        {"sub": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", "aud": "authenticated", "exp": int(time.time()) + 600},
        SECRET,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {tok}"}


def event():
    return {
        "schema_version": 1,
        "event_id": str(uuid.uuid4()),
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "source": "driftwatch-demo-bot",
        "signal": "embedding_drift",
        "value": 0.2,
    }


def client_with(transport):
    store = SupabaseSignalStore("https://example.supabase.co", "anon-key", transport=transport)
    app = FastAPI()
    app.include_router(build_router(store))
    return TestClient(app)


def test_accepted_returns_202():
    def handler(request):
        assert request.headers["authorization"].startswith("Bearer ")
        assert request.headers["apikey"] == "anon-key"
        body = json.loads(request.content)
        assert body["project_id"] == PROJECT
        return httpx.Response(201)

    resp = client_with(httpx.MockTransport(handler)).post(
        f"/v1/events?project_id={PROJECT}", json=event(), headers=bearer()
    )
    assert resp.status_code == 202
    assert resp.json()["status"] == "accepted"


def test_retry_hits_unique_constraint_and_reports_duplicate():
    resp = client_with(httpx.MockTransport(lambda r: httpx.Response(409))).post(
        f"/v1/events?project_id={PROJECT}", json=event(), headers=bearer()
    )
    assert resp.status_code == 202
    assert resp.json()["status"] == "duplicate"


def test_rls_denial_becomes_403():
    resp = client_with(httpx.MockTransport(lambda r: httpx.Response(403))).post(
        f"/v1/events?project_id={PROJECT}", json=event(), headers=bearer()
    )
    assert resp.status_code == 403


def test_upstream_outage_is_503_without_leaking_detail():
    def boom(request):
        raise httpx.ConnectError("connection refused to db.internal:5432")

    resp = client_with(httpx.MockTransport(boom)).post(
        f"/v1/events?project_id={PROJECT}", json=event(), headers=bearer()
    )
    assert resp.status_code == 503
    assert "db.internal" not in resp.text


def test_no_token_is_401_and_nothing_is_sent():
    calls = []
    resp = client_with(httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(201))).post(
        f"/v1/events?project_id={PROJECT}", json=event()
    )
    assert resp.status_code == 401
    assert calls == []


def test_contract_violation_is_422_and_nothing_is_sent():
    calls = []
    bad = event()
    bad["signal"] = "not_a_signal"
    resp = client_with(httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(201))).post(
        f"/v1/events?project_id={PROJECT}", json=bad, headers=bearer()
    )
    assert resp.status_code == 422
    assert calls == []


def test_non_uuid_project_is_422():
    resp = client_with(httpx.MockTransport(lambda r: httpx.Response(201))).post(
        "/v1/events?project_id=not-a-uuid", json=event(), headers=bearer()
    )
    assert resp.status_code == 422


def test_store_raises_on_unexpected_status():
    store = SupabaseSignalStore(
        "https://example.supabase.co", "k", transport=httpx.MockTransport(lambda r: httpx.Response(500))
    )
    from monitor.cloud.ingest import validate_event

    with pytest.raises(SupabaseStoreError):
        store.insert("tok", PROJECT, validate_event(event()))
