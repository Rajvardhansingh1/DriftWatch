"""The CLI's only network client: PostgREST RPC calls to the pinned DriftWatch project.

It sends the publishable key and nothing else (no session, no service key). Every error becomes a
fixed, user-safe sentence: request bodies (device codes, API keys) and raw server text never appear.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import httpx

from driftwatch_llm import __version__
from driftwatch_llm.endpoints import Endpoints
from driftwatch_llm.secrets import KEY_RE
from driftwatch_llm.validate import clean_text, is_uuid

_DEVICE_CODE_RE = re.compile(r"^[0-9a-f]{64}$")
_USER_CODE_RE = re.compile(r"^[BCDFGHJKLMNPQRSTVWXZ]{8}$")
_STATUSES = {"authorization_pending", "slow_down", "approved", "access_denied", "expired_token", "key_limit"}
_UNEXPECTED = "Unexpected response from DriftWatch. Try again, or update driftwatch-llm."
_UNREACHABLE = "Could not reach DriftWatch. Check your connection and try again."


class ApiError(Exception):
    """A failed call. The message is safe to print."""


@dataclass(frozen=True)
class DeviceStart:
    device_code: str
    user_code: str
    expires_in: int
    interval: int


@dataclass(frozen=True)
class PollResult:
    status: str
    api_key: str | None = None
    project_id: str | None = None
    project_name: str | None = None

    def __repr__(self) -> str:  # never let a key reach a log line through repr()
        return f"PollResult(status={self.status!r}, project_id={self.project_id!r})"


def _is_int(value: object, low: int, high: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def _error_for(status: int, body: object) -> ApiError:
    code = body.get("code") if isinstance(body, dict) else None
    message = body.get("message") if isinstance(body, dict) else None
    if code == "PT429" or status == 429:
        return ApiError("Too many sign-in requests. Try again in a minute.")
    if code == "PT422":
        # PT422 texts are written by our own SQL; anything long or odd gets a fixed sentence.
        text = clean_text(message, 120)
        return ApiError(text if text and isinstance(message, str) and len(message) <= 120 else "That request was not accepted.")
    if status in (401, 403):
        return ApiError("Your request was not accepted.")
    return ApiError(f"DriftWatch had a problem (HTTP {status}). Try again later.")


class Api:
    def __init__(
        self,
        endpoints: Endpoints,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 15.0,
    ) -> None:
        self._ep = endpoints
        self._transport = transport
        self._timeout = timeout

    def _rpc(self, fn: str, body: dict[str, Any], *, want_json: bool = True) -> Any:
        url = f"{self._ep.supabase_url}/rest/v1/rpc/{fn}"
        headers = {
            "apikey": self._ep.publishable_key,
            "content-type": "application/json",
            "user-agent": f"driftwatch-llm/{__version__}",
        }
        try:
            with httpx.Client(transport=self._transport, timeout=self._timeout, follow_redirects=False) as client:
                response = client.post(url, json=body, headers=headers)
        except httpx.HTTPError:
            raise ApiError(_UNREACHABLE) from None
        if response.status_code >= 400:
            try:
                parsed: object = response.json()
            except ValueError:
                parsed = None
            raise _error_for(response.status_code, parsed)
        if not want_json:
            return None
        try:
            return response.json()
        except ValueError:
            raise ApiError(_UNEXPECTED) from None

    def start_device_login(self, device_name: str, device_os: str) -> DeviceStart:
        data = self._rpc("start_device_login", {"p_device_name": device_name, "p_device_os": device_os})
        if not isinstance(data, dict):
            raise ApiError(_UNEXPECTED)
        device_code, user_code = data.get("device_code"), data.get("user_code")
        expires_in, interval = data.get("expires_in"), data.get("interval")
        if (
            not isinstance(device_code, str) or not _DEVICE_CODE_RE.match(device_code)
            or not isinstance(user_code, str) or not _USER_CODE_RE.match(user_code)
            or not _is_int(expires_in, 1, 3600) or not _is_int(interval, 1, 60)
        ):
            raise ApiError(_UNEXPECTED)
        return DeviceStart(device_code=device_code, user_code=user_code, expires_in=expires_in, interval=interval)

    def poll_device_login(self, device_code: str) -> PollResult:
        data = self._rpc("poll_device_login", {"p_device_code": device_code})
        if not isinstance(data, dict):
            raise ApiError(_UNEXPECTED)
        status = data.get("status")
        if status not in _STATUSES:
            raise ApiError(_UNEXPECTED)
        if status != "approved":
            if "api_key" in data:
                raise ApiError(_UNEXPECTED)  # a key outside "approved" is never accepted
            return PollResult(status=status)
        key, project_id = data.get("api_key"), data.get("project_id")
        if not isinstance(key, str) or not KEY_RE.match(key) or not is_uuid(project_id):
            raise ApiError(_UNEXPECTED)
        return PollResult(
            status="approved",
            api_key=key,
            project_id=project_id,
            project_name=clean_text(data.get("project_name")) or "your project",
        )

    def revoke_api_key(self, api_key: str) -> None:
        self._rpc("revoke_api_key_by_secret", {"p_api_key": api_key}, want_json=False)
