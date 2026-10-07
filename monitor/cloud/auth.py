"""Verifies a Supabase Auth access token locally (Spec_Upgrade.md section
5.1). This is the boundary between "a request has a token" and "a
request is authenticated as a specific user" - it does not itself decide
authorization (org/project membership, role) for anything; RLS on the
Supabase side and per-route authorization checks on top of this handle
that (section 5.3). A valid token proves identity, never tenant access.

Tokens are verified with ES256/RS256 against the project's JWKS (fetched
from SUPABASE_URL and cached) or with HS256 using the legacy shared
secret. The algorithm is chosen from a fixed allow-list (anything else,
including "none", is rejected) and then pinned: PyJWT is told to accept
only that algorithm, and the JWKS key's own algorithm must match it. `iss`
is enforced only when SUPABASE_URL is set; local-only mode (no
SUPABASE_URL) has neither a JWKS nor an issuer to check.

Deliberately does not use supabase-py: verification is local with PyJWT,
so there is no network round-trip per request beyond the cached JWKS."""
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
            signing_key = client.get_signing_key_from_jwt(token)
        except Exception as exc:  # JWKS fetch/lookup failure is an auth failure, not a 500
            raise AuthError("invalid access token: signing key not found") from exc
        if signing_key.algorithm_name != alg:
            raise AuthError("invalid access token: key/algorithm mismatch")
        key = signing_key.key
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
    except (jwt.PyJWTError, TypeError, ValueError) as exc:
        raise AuthError(f"invalid access token: {exc}") from exc

    if not isinstance(claims["sub"], str) or not claims["sub"]:
        raise AuthError("access token missing subject claim")

    return AuthenticatedUser(
        user_id=claims["sub"], email=claims.get("email"), aal=claims.get("aal", "aal1")
    )
