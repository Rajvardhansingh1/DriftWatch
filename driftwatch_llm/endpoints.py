"""Where the CLI talks to. Pinned in the package so a project's own files can never redirect it.

Only the global `--dev` flag lets `DRIFTWATCH_DEV_*` environment variables override these values,
and even then plain http is accepted only for loopback hosts.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlsplit


class EndpointError(ValueError):
    """A dev endpoint override was refused. The message names the setting, never its value."""


@dataclass(frozen=True)
class Endpoints:
    supabase_url: str
    publishable_key: str  # public by design: it only identifies the project to the API gateway
    web_origin: str
    relay_url: str = "https://driftwatch-monitor.onrender.com"  # the free allowance's relay (Render)


PINNED = Endpoints(
    supabase_url="https://zaodlvgqowhdqobvvhpx.supabase.co",
    publishable_key="sb_publishable_mMch89F43lrLgpGHPKbhgg_Z43-lzes",
    web_origin="https://drift-watch-rouge.vercel.app",
)

_LOOPBACK = {"localhost", "127.0.0.1", "::1"}


def _checked_url(setting: str, value: str) -> str:
    parts = urlsplit(value)
    if parts.username or parts.password:
        raise EndpointError(f"{setting} must not contain credentials")
    if parts.scheme == "https" and parts.hostname:
        return value.rstrip("/")
    if parts.scheme == "http" and parts.hostname in _LOOPBACK:
        return value.rstrip("/")
    raise EndpointError(f"{setting} must be an https URL, or http on localhost")


def resolve(dev: bool, env: Mapping[str, str] | None = None) -> Endpoints:
    if not dev:
        return PINNED
    env = os.environ if env is None else env

    def pick(name: str, fallback: str, *, url: bool = True) -> str:
        raw = (env.get(name) or "").strip()
        if not raw:
            return fallback
        return _checked_url(name, raw) if url else raw

    return Endpoints(
        supabase_url=pick("DRIFTWATCH_DEV_SUPABASE_URL", PINNED.supabase_url),
        publishable_key=pick("DRIFTWATCH_DEV_SUPABASE_KEY", PINNED.publishable_key, url=False),
        web_origin=pick("DRIFTWATCH_DEV_WEB_ORIGIN", PINNED.web_origin),
        relay_url=pick("DRIFTWATCH_DEV_RELAY_URL", PINNED.relay_url),
    )
