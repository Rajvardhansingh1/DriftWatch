"""Platform-operator authorization (Spec_Upgrade.md section 5.4, 12.3).
Separate from customer organization roles. Membership is an explicit
allowlist from configuration; it is never inferred from email domain,
user metadata, or an organization role."""
from __future__ import annotations

import logging

from monitor.config import settings

audit_log = logging.getLogger("driftwatch.audit")


def platform_admin_ids() -> frozenset[str]:
    return frozenset(
        part.strip() for part in settings.platform_admin_user_ids.split(",") if part.strip()
    )


def is_platform_admin(user_id: str) -> bool:
    return bool(user_id) and user_id in platform_admin_ids()


def record_admin_action(user_id: str, action: str, result: str) -> None:
    # Audit trail (spec 13.3): actor, action, result. Never prompt/response
    # or secret content.
    audit_log.info("admin_action actor=%s action=%s result=%s", user_id, action, result)
