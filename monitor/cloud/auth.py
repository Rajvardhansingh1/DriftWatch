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

from monitor.config import settings


class AuthError(Exception):
    """A request's bearer token is missing, malformed, expired, or
    signed with the wrong secret. Callers should turn this into a 401,
    never a 500 - an invalid token is an expected client condition, not
    a server fault."""


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: str  # Supabase auth.users.id (uuid, as a string)
    email: str | None = None


def verify_access_token(token: str) -> AuthenticatedUser:
    if not settings.supabase_jwt_secret:
        raise AuthError("cloud auth is not configured (SUPABASE_JWT_SECRET unset)")
    if not token:
        raise AuthError("missing access token")

    try:
        claims = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("access token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError(f"invalid access token: {exc}") from exc

    subject = claims.get("sub")
    if not subject:
        raise AuthError("access token missing subject claim")

    return AuthenticatedUser(user_id=subject, email=claims.get("email"))
