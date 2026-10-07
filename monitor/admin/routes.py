from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from monitor.admin.access import is_platform_admin, record_admin_action
from monitor.cloud.auth import AuthError, verify_access_token

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    return authorization.removeprefix("Bearer ").strip()


@router.get("/status")
def admin_status(authorization: str | None = Header(default=None)):
    try:
        user = verify_access_token(_bearer(authorization))
    except AuthError:
        raise HTTPException(status_code=401, detail="invalid or expired token")

    if not is_platform_admin(user.user_id):
        record_admin_action(user.user_id, "admin_status", "denied")
        raise HTTPException(status_code=403, detail="platform admin required")

    if user.aal != "aal2":
        record_admin_action(user.user_id, "admin_status", "denied_no_mfa")
        raise HTTPException(status_code=403, detail="multi-factor authentication required")

    record_admin_action(user.user_id, "admin_status", "ok")
    return {"status": "ok", "scope": "platform_admin"}
