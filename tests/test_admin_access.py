import time

import jwt
import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from monitor.admin.routes import router
from monitor.config import settings

SECRET = "test-jwt-secret-do-not-use-in-production-0123456789"
ADMIN_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "supabase_jwt_secret", SECRET)
    monkeypatch.setattr(settings, "platform_admin_user_ids", ADMIN_ID)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def token_for(sub, email=None):
    claims = {"sub": sub, "aud": "authenticated", "exp": int(time.time()) + 600}
    if email:
        claims["email"] = email
    return jwt.encode(claims, SECRET, algorithm="HS256")


def test_no_token_is_401(client):
    assert client.get("/api/admin/status").status_code == 401


def test_bad_token_is_401(client):
    resp = client.get("/api/admin/status", headers={"Authorization": "Bearer nonsense"})
    assert resp.status_code == 401


def test_authenticated_non_admin_is_403(client):
    resp = client.get(
        "/api/admin/status", headers={"Authorization": f"Bearer {token_for(USER_ID)}"}
    )
    assert resp.status_code == 403


def test_admin_email_domain_does_not_grant_access(client):
    # Spec 5.4: never infer platform admin from email/metadata.
    resp = client.get(
        "/api/admin/status",
        headers={"Authorization": f"Bearer {token_for(USER_ID, email='admin@driftwatch.io')}"},
    )
    assert resp.status_code == 403


def test_allowlisted_admin_is_200(client):
    resp = client.get(
        "/api/admin/status", headers={"Authorization": f"Bearer {token_for(ADMIN_ID)}"}
    )
    assert resp.status_code == 200
    assert resp.json()["scope"] == "platform_admin"


def test_empty_allowlist_grants_nobody(client, monkeypatch):
    monkeypatch.setattr(settings, "platform_admin_user_ids", "")
    resp = client.get(
        "/api/admin/status", headers={"Authorization": f"Bearer {token_for(ADMIN_ID)}"}
    )
    assert resp.status_code == 403
