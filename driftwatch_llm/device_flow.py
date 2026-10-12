"""Browser sign-in for the CLI (RFC 8628 device authorization).

The CLI shows a short code and a link, the user approves on the website, and the CLI polls until it
receives a project key. Time, sleeping, printing and the browser are injected so tests need no
network and no real waiting.
"""

from __future__ import annotations

import time
import webbrowser
from typing import Callable
from urllib.parse import quote

from driftwatch_llm.api import Api, ApiError, PollResult

_MAX_CONSECUTIVE_ERRORS = 3


class LoginDenied(Exception):
    """The user chose Deny on the website."""


class LoginExpired(Exception):
    """The code expired before anyone approved it."""


class LoginFailed(Exception):
    """Sign-in could not finish. The message is safe to print."""


def run_device_login(
    api: Api,
    *,
    device_name: str,
    device_os: str,
    web_origin: str,
    open_browser: bool = True,
    echo: Callable[[str], None] = print,
    open_url: Callable[[str], object] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> PollResult:
    start = api.start_device_login(device_name, device_os)
    dashed = f"{start.user_code[:4]}-{start.user_code[4:]}"
    url = f"{web_origin}/auth/device?code={quote(dashed)}"

    echo(f"Your code: {dashed}")
    echo("Open this link in your browser to approve it:")
    echo(f"  {url}")
    echo("Only approve this if you started it yourself.")
    if open_browser:
        opener = open_url or webbrowser.open
        try:
            opened = bool(opener(url))
        except Exception:  # noqa: BLE001 - a missing browser must never stop sign-in
            opened = False
        if not opened:
            echo("Could not open a browser here. Open the link above yourself.")
    echo("Waiting for approval (Ctrl+C to cancel)...")

    deadline = clock() + start.expires_in
    interval = float(start.interval)
    errors = 0
    while True:
        sleep(interval)
        try:
            result = api.poll_device_login(start.device_code)
            errors = 0
        except ApiError as exc:
            errors += 1
            if errors > _MAX_CONSECUTIVE_ERRORS:
                raise LoginFailed(str(exc)) from None
            if clock() >= deadline:
                raise LoginExpired("The sign-in code expired. Run the command again.") from None
            continue

        if result.status == "approved":
            return result
        if result.status == "access_denied":
            raise LoginDenied("The sign-in was denied.")
        if result.status == "expired_token":
            raise LoginExpired("The sign-in code expired. Run the command again.")
        if result.status == "key_limit":
            raise LoginFailed("This project already has 10 active keys. Revoke one on the website and try again.")
        if result.status == "slow_down":
            interval += 5
        if clock() >= deadline:
            raise LoginExpired("The sign-in code expired. Run the command again.")
