import time

import jwt
import pytest

from monitor.cloud.auth import AuthError, verify_access_token
from monitor.config import settings

TEST_SECRET = "test-jwt-secret-do-not-use-in-production-0123456789"


@pytest.fixture(autouse=True)
def configured_jwt_secret(monkeypatch):
    monkeypatch.setattr(settings, "supabase_jwt_secret", TEST_SECRET)
    monkeypatch.setattr(settings, "supabase_url", "")


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
    with pytest.raises(AuthError, match="sub"):
        verify_access_token(token)


def test_empty_token_raises_auth_error():
    with pytest.raises(AuthError, match="missing access token"):
        verify_access_token("")


def test_unconfigured_secret_raises_auth_error(monkeypatch):
    monkeypatch.setattr(settings, "supabase_jwt_secret", "")
    with pytest.raises(AuthError, match="not configured"):
        verify_access_token(make_token())


from cryptography.hazmat.primitives.asymmetric import ec

import monitor.cloud.auth as auth_module


class _FakeJwks:
    def __init__(self, key):
        self._key = key

    def get_signing_key_from_jwt(self, token):
        class _K:
            pass

        k = _K()
        k.key = self._key.public_key()
        return k


def _es256_token(private_key, **claims):
    payload = {"sub": "11111111-1111-1111-1111-111111111111", "aud": "authenticated",
               "exp": int(time.time()) + 600, **claims}
    return jwt.encode(payload, private_key, algorithm="ES256")


def test_es256_token_verified_through_jwks(monkeypatch):
    key = ec.generate_private_key(ec.SECP256R1())
    monkeypatch.setattr(auth_module, "_jwks", lambda: _FakeJwks(key))
    assert verify_access_token(_es256_token(key, aal="aal2")).aal == "aal2"


def test_es256_token_signed_by_other_key_is_rejected(monkeypatch):
    good, evil = ec.generate_private_key(ec.SECP256R1()), ec.generate_private_key(ec.SECP256R1())
    monkeypatch.setattr(auth_module, "_jwks", lambda: _FakeJwks(good))
    with pytest.raises(AuthError):
        verify_access_token(_es256_token(evil))


def test_alg_none_token_is_rejected():
    token = jwt.encode({"sub": "x", "aud": "authenticated", "exp": int(time.time()) + 600},
                       key=None, algorithm="none")
    with pytest.raises(AuthError, match="unsupported algorithm"):
        verify_access_token(token)


def test_hs256_with_unconfigured_secret_is_rejected():
    token = jwt.encode({"sub": "x", "aud": "authenticated", "exp": int(time.time()) + 600},
                       "not-the-configured-secret-but-long-enough-0000000000", algorithm="HS256")
    with pytest.raises(AuthError):
        verify_access_token(token)


def test_issuer_is_enforced_when_supabase_url_is_set(monkeypatch):
    monkeypatch.setattr(settings, "supabase_url", "https://proj.supabase.co")
    with pytest.raises(AuthError):
        verify_access_token(make_token())  # no iss claim
    assert verify_access_token(make_token(iss="https://proj.supabase.co/auth/v1")).user_id
