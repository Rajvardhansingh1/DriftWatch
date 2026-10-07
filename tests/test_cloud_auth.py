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
    def __init__(self, key, algorithm_name=None):
        self._key = key
        self._alg = algorithm_name or ("ES256" if isinstance(key, ec.EllipticCurvePrivateKey) else "RS256")

    def get_signing_key_from_jwt(self, token):
        class _K:
            pass

        k = _K()
        k.key = self._key.public_key()
        k.algorithm_name = self._alg
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


from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402


def _claims():
    return {"sub": "11111111-1111-1111-1111-111111111111", "aud": "authenticated",
            "exp": int(time.time()) + 600}


def test_es256_header_with_rsa_jwks_key_is_auth_error(monkeypatch):
    ec_key = ec.generate_private_key(ec.SECP256R1())
    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(auth_module, "_jwks", lambda: _FakeJwks(rsa_key))
    with pytest.raises(AuthError, match="mismatch"):
        verify_access_token(_es256_token(ec_key))


def test_rs256_header_with_ec_jwks_key_is_auth_error(monkeypatch):
    ec_key = ec.generate_private_key(ec.SECP256R1())
    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(auth_module, "_jwks", lambda: _FakeJwks(ec_key))
    with pytest.raises(AuthError, match="mismatch"):
        verify_access_token(jwt.encode(_claims(), rsa_key, algorithm="RS256"))


def test_wrong_key_type_that_claims_right_algorithm_is_auth_error_not_typeerror(monkeypatch):
    # Defence in depth: even if the algorithm check were bypassed, decode errors map to 401.
    ec_key = ec.generate_private_key(ec.SECP256R1())
    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(auth_module, "_jwks", lambda: _FakeJwks(rsa_key, algorithm_name="ES256"))
    with pytest.raises(AuthError):
        verify_access_token(_es256_token(ec_key))


def test_empty_subject_is_rejected():
    with pytest.raises(AuthError, match="subject"):
        verify_access_token(make_token(sub=""))


def test_jwks_fetch_failure_is_auth_error(monkeypatch):
    class _Boom:
        def get_signing_key_from_jwt(self, token):
            raise RuntimeError("network down")

    monkeypatch.setattr(auth_module, "_jwks", lambda: _Boom())
    with pytest.raises(AuthError):
        verify_access_token(_es256_token(ec.generate_private_key(ec.SECP256R1())))


def test_asymmetric_token_without_jwks_configured_is_auth_error(monkeypatch):
    monkeypatch.setattr(auth_module, "_jwks", lambda: None)
    with pytest.raises(AuthError, match="not configured"):
        verify_access_token(_es256_token(ec.generate_private_key(ec.SECP256R1())))
