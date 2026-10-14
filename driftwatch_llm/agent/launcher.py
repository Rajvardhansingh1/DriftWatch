"""Starting the agent exactly once, from any number of processes at the same time.

`ensure_agent()` first tries to talk to a running agent. If there is none it takes a short `spawn.lock`,
checks again, and only then starts one detached process. The agent itself holds `agent.lock` for its whole
life, so even if two starters did spawn, only one agent survives. A failed start is not retried for
`retry_after` seconds (no spawn storms from a broken install).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

from driftwatch_llm.agent.ipc import IpcClient, agent_dir
from driftwatch_llm.agent.lock import FileLock

SPAWN_LOCK_WAIT = 3.0
START_WAIT = 8.0
RETRY_AFTER = 60.0
RESPAWN_PAUSE = 1.5  # between a first spawn that died instantly and its single retry


def _alive(client: IpcClient) -> bool:
    reply = client.send({"type": "heartbeat", "pid": os.getpid()})
    return bool(reply and reply.get("ok"))


def _recent_failure(marker: Path, retry_after: float) -> bool:
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
        return data.get("ok") is False and time.time() - float(data["ts"]) < retry_after
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _write_marker(marker: Path, ok: bool) -> None:
    try:
        marker.write_text(json.dumps({"ts": time.time(), "ok": ok}), encoding="utf-8")
    except OSError:
        pass


def _wait_until_alive(
    client: IpcClient, seconds: float, child: "subprocess.Popen | None" = None, cancelled: Callable[[], bool] = lambda: False
) -> bool:
    deadline = time.monotonic() + seconds
    exited_at: float | None = None
    while time.monotonic() < deadline:
        if _alive(client):
            return True
        if cancelled():
            return False
        if child is not None and child.poll() is not None:
            # The child is gone. It may have lost the lock race to an agent that is just coming up, so
            # allow a short grace period, then call it a failed start (fast, instead of waiting it all out).
            exited_at = exited_at or time.monotonic()
            if time.monotonic() - exited_at > 1.0:
                return False
        time.sleep(0.1)
    return False


def _command() -> list[str]:
    override = os.environ.get("DRIFTWATCH_AGENT_CMD")  # testing hook: a JSON list
    if override:
        cmd = json.loads(override)
        if isinstance(cmd, list) and cmd and all(isinstance(c, str) for c in cmd):
            return cmd
    return [sys.executable, "-m", "driftwatch_llm.agent"]


def _spawn(home: Path | str | None, workdir: Path) -> "subprocess.Popen":
    env = {**os.environ, "DRIFTWATCH_DISABLE": "1"}  # the agent never captures itself
    if home is not None:
        env["DRIFTWATCH_HOME"] = str(home)
    kwargs: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
        "env": env,
        # Not the caller's directory: `python -m` puts the working directory first on sys.path, and a
        # project folder is not somewhere the agent should import from.
        "cwd": str(workdir),
    }
    if sys.platform == "win32":
        base = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        try:  # leave the caller's job object (a terminal closing must not kill the agent), if allowed
            return subprocess.Popen(_command(), creationflags=base | subprocess.CREATE_BREAKAWAY_FROM_JOB, **kwargs)
        except OSError:
            return subprocess.Popen(_command(), creationflags=base, **kwargs)
    return subprocess.Popen(_command(), start_new_session=True, **kwargs)


def ensure_agent(
    home: Path | str | None = None,
    wait: float = START_WAIT,
    retry_after: float = RETRY_AFTER,
    cancelled: Callable[[], bool] = lambda: False,
) -> bool:
    """True when an agent is answering (it may have been started just now).

    `cancelled` lets a caller that is shutting down cut the waits short; a cancelled attempt records no outcome."""
    client = IpcClient(home, io_timeout=0.5)
    try:
        if _alive(client):
            return True
        d = agent_dir(home)
        d.mkdir(parents=True, exist_ok=True)
        marker = d / "spawn.json"
        if _recent_failure(marker, retry_after):
            return False
        lock = FileLock(d / "spawn.lock")
        deadline = time.monotonic() + SPAWN_LOCK_WAIT
        got = lock.acquire()
        while not got and time.monotonic() < deadline:
            time.sleep(0.05)
            if _alive(client):
                return True
            got = lock.acquire()
        if not got:
            return _wait_until_alive(client, wait, cancelled=cancelled)  # someone else is starting it
        try:
            if _alive(client):
                return True
            if _recent_failure(marker, retry_after):
                return False
            # The marker is written only once the outcome is known: writing "failed" up front would make
            # every concurrent starter think the start had already failed and give up.
            child = _spawn(home, d)
            up = _wait_until_alive(client, wait, child, cancelled)
            if not up and cancelled():
                return False  # shutting down: the outcome is unknown, so nothing is recorded
            if not up and child.poll() is not None:
                # The child died at once: usually an agent that was just stopped and still holds its OS lock for a
                # moment (`agent stop`, then an immediate app start). One short pause and one more try, before the
                # outcome is recorded: a failure marker blocks every starter for the next minute.
                for _ in range(int(RESPAWN_PAUSE / 0.1)):
                    if cancelled():
                        return False
                    time.sleep(0.1)
                if _alive(client):
                    up = True
                else:
                    child = _spawn(home, d)
                    up = _wait_until_alive(client, wait, child, cancelled)
                    if not up and cancelled():
                        return False
            _write_marker(marker, ok=up)
            return up
        finally:
            lock.release()
    finally:
        client.close()
