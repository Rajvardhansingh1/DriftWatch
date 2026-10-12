"""The autostart hook: runs at interpreter start (from the opt-in .pth file, or `driftwatch run`).

Rules:

- Standard library only until a project config is actually found: a process outside any project costs a
  few directory checks and imports nothing else. Budget in a trusted project: 200 ms.
- It never raises, never prints (except one notice a day per untrusted folder), never touches the network
  and never starts a thread or process at boot. Capture is installed, but the sender thread (and the
  agent) start only when the first LLM response is actually captured.
- It acts only in a folder whose `.driftwatch/config.toml` the user trusted (Plan 3 trust store), for the
  very project id they trusted. A cloned repository's config does nothing (hardening item C1).
- The `driftwatch` CLI, `pip` and the agent itself are never hooked. `DRIFTWATCH_DISABLE=1` turns it off.
"""

from __future__ import annotations

import os
import sys

_CONFIG = os.path.join(".driftwatch", "config.toml")
_SKIP = {"driftwatch", "pip", "pip3", "ensurepip", "venv", "virtualenv"}
_NOTICE = (
    "driftwatch: this folder has a .driftwatch config that you have not trusted, so monitoring is off here. "
    "Run `driftwatch trust` to review it.\n"
)


def _skipped(orig_argv: list[str] | None) -> bool:
    args = list(orig_argv or [])[1:]
    target = ""
    if args and args[0] == "-m" and len(args) > 1:
        target = args[1]
    elif args and not args[0].startswith("-"):
        target = args[0].replace("\\", "/").rsplit("/", 1)[-1]  # both separators: a Windows path is not split by POSIX basename
    base = target.split(".")[0].lower()
    return base in _SKIP or target.startswith("driftwatch_llm")


def _script_dir() -> str | None:
    args = list(getattr(sys, "orig_argv", None) or [])[1:]
    if args and not args[0].startswith("-") and os.path.isfile(args[0]):
        return os.path.dirname(os.path.abspath(args[0]))
    return None


def _find_root(starts: list[str]) -> str | None:
    for start in starts:
        d = os.path.abspath(start)
        for _ in range(64):
            if os.path.isfile(os.path.join(d, _CONFIG)):
                return d
            parent = os.path.dirname(d)
            if parent == d:
                break
            d = parent
    return None


def _notice_once(root: str) -> None:
    import hashlib
    import json
    import time

    from driftwatch_llm import paths

    path = os.path.join(str(paths.config_dir()), "notice.json")
    key = hashlib.sha256(os.path.normcase(os.path.abspath(root)).encode("utf-8")).hexdigest()[:16]
    now = time.time()
    try:
        with open(path, encoding="utf-8") as f:
            seen = json.load(f)
        if not isinstance(seen, dict):
            seen = {}
    except (OSError, ValueError):
        seen = {}
    if now - float(seen.get(key, 0) or 0) < 86400:
        return
    seen[key] = now
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(seen, f)
    sys.stderr.write(_NOTICE)


def _boot() -> None:
    if os.environ.get("DRIFTWATCH_DISABLE"):
        return
    if _skipped(getattr(sys, "orig_argv", None)):
        return
    starts = [p for p in (_script_dir(), os.getcwd()) if p]  # the code being run first, then where it was launched
    root = _find_root(starts)
    if root is None:
        return  # not in a DriftWatch project: nothing else is imported
    from pathlib import Path

    from driftwatch_llm.project import read_config
    from driftwatch_llm.trust import TrustStore

    cfg = read_config(Path(root))
    if cfg is None:
        return
    if not TrustStore().is_trusted(Path(root), cfg.project_id):
        _notice_once(root)
        return

    from driftwatch_llm.capture import wrappers
    from driftwatch_llm.capture.client import CaptureClient

    client = CaptureClient(cfg.project_id)
    wrappers.set_sink(client.submit_and_start)  # the sender thread starts with the first captured response
    wrappers.patch_loaded()
    wrappers.install_import_hook()


def boot() -> None:
    try:
        _boot()
    except Exception:  # noqa: BLE001 - a hook that runs in every Python process must never break one
        pass
