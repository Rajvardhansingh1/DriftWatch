"""Verifies a Supabase Auth access token locally (Spec_Upgrade.md section
5.1). This is the boundary between "a request has a token" and "a
request is authenticated as a specific user" - it does not itself decide
authorization (org/project membership, role) for anything; RLS on the
Supabase side and per-route authorization checks on top of this handle
that (section 5.3). A valid token proves identity, never tenant access.

Deliberately does not use supabase-py: a Supabase Auth access token is a
standard JWT signed with the project's JWT secret (HS256, legacy
symmetric signing - the same secret configured for this project). Local
HS256 verification needs no network round-trip per request and no new
heavyweight dependency beyond PyJWT, which is already a transitive
dependency of most JWT-consuming stacks."""
from __future__ import annotations

from dataclasses import dataclass

import jwt
from jwt import PyJWKClient

from monitor.config import settings

_ASYMMETRIC = ("ES256", "RS256")
_jwks_client: PyJWKClient | None = None


class AuthError(Exception):
    """A request's bearer token is missing, malformed, expired, or signed
    with the wrong key. Callers turn this into a 401, never a 500."""


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: str  # Supabase auth.users.id (uuid, as a string)
    email: str | None = None
    aal: str = "aal1"  # authenticator assurance level; aal2 means MFA was used


def _jwks() -> PyJWKClient | None:
    global _jwks_client
    if _jwks_client is None and settings.supabase_url:
        _jwks_client = PyJWKClient(
            f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json",
            cache_keys=True,
            lifespan=600,
        )
    return _jwks_client


def verify_access_token(token: str) -> AuthenticatedUser:
    if not token:
        raise AuthError("missing access token")

    try:
        alg = jwt.get_unverified_header(token).get("alg")
    except jwt.InvalidTokenError as exc:
        raise AuthError(f"invalid access token: {exc}") from exc

    # The header only selects from our own allow-list; PyJWT is then told to
    # accept exactly that one algorithm, so alg-confusion cannot happen.
    if alg in _ASYMMETRIC:
        client = _jwks()
        if client is None:
            raise AuthError("cloud auth is not configured (SUPABASE_URL unset)")
        try:
            key = client.get_signing_key_from_jwt(token).key
        except Exception as exc:  # JWKS fetch/lookup failure is an auth failure, not a 500
            raise AuthError("invalid access token: signing key not found") from exc
    elif alg == "HS256":
        if not settings.supabase_jwt_secret:
            raise AuthError("cloud auth is not configured (SUPABASE_JWT_SECRET unset)")
        key = settings.supabase_jwt_secret
    else:
        raise AuthError("invalid access token: unsupported algorithm")

    required = ["exp", "sub", "aud"]
    kwargs: dict = {}
    if settings.supabase_url:
        kwargs["issuer"] = f"{settings.supabase_url.rstrip('/')}/auth/v1"
        required.append("iss")

    try:
        claims = jwt.decode(
            token, key, algorithms=[alg], audience="authenticated",
            options={"require": required}, **kwargs,
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("access token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError(f"invalid access token: {exc}") from exc

    return AuthenticatedUser(
        user_id=claims["sub"], email=claims.get("email"), aal=claims.get("aal", "aal1")
    )
