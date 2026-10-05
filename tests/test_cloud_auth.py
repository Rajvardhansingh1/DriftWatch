import time

import jwt
import pytest

from monitor.cloud.auth import AuthError, verify_access_token
from monitor.config import settings

TEST_SECRET = "test-jwt-secret-do-not-use-in-production-0123456789"


@pytest.fixture(autouse=True)
def configured_jwt_secret(monkeypatch):
    monkeypatch.setattr(settings, "supabase_jwt_secret", TEST_SECRET)


def make_token(secret=TEST_SECRET, sub="11111111-1111-1111-1111-111111111111", exp_delta=3600, **extra):
    payload = {
        "sub": sub,
        "aud": "authenticated",
        "exp": int(time.time()) + exp_delta,
        **extra,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def test_valid_token_returns_authenticated_user():
    token = make_token(email="a@example.com")
    user = verify_access_token(token)
    assert user.user_id == "11111111-1111-1111-1111-111111111111"
    assert user.email == "a@example.com"


def test_expired_token_raises_auth_error():
    token = make_token(exp_delta=-10)
    with pytest.raises(AuthError, match="expired"):
        verify_access_token(token)


def test_wrong_secret_raises_auth_error():
    token = make_token(secret="a-different-secret-that-is-also-long-enough")
    with pytest.raises(AuthError, match="invalid access token"):
        verify_access_token(token)


def test_missing_subject_claim_raises_auth_error():
    token = jwt.encode(
        {"aud": "authenticated", "exp": int(time.time()) + 3600}, TEST_SECRET, algorithm="HS256"
    )
    with pytest.raises(AuthError, match="missing subject"):
        verify_access_token(token)


def test_empty_token_raises_auth_error():
    with pytest.raises(AuthError, match="missing access token"):
        verify_access_token("")


def test_unconfigured_secret_raises_auth_error(monkeypatch):
    monkeypatch.setattr(settings, "supabase_jwt_secret", "")
    with pytest.raises(AuthError, match="not configured"):
        verify_access_token(make_token())
