"""Gets captured responses from the user's process to the local agent without ever blocking the app.

`submit()` appends to a bounded queue and returns (the oldest record is dropped, and counted, when the queue
is full). A daemon thread does everything else: it says hello, starts the agent if none is running (at most
once a minute), sends the records, and sends a heartbeat with counters every few seconds. Nothing here
raises into the caller, and the heavy imports (multiprocessing.connection) happen in that thread, not at
startup.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections import deque
from typing import Any

from driftwatch_llm.capture import wrappers

HEARTBEAT_EVERY = 5.0
ENSURE_EVERY = 60.0
QUEUE_SIZE = 200


class CaptureClient:
    def __init__(
        self,
        project_id: str,
        home: Any = None,
        queue_size: int = QUEUE_SIZE,
        heartbeat_every: float = HEARTBEAT_EVERY,
        ensure_every: float = ENSURE_EVERY,
    ) -> None:
        self._project_id = project_id
        self._home = home
        self._queue: deque[dict[str, Any]] = deque(maxlen=queue_size)
        self._heartbeat_every = heartbeat_every
        self._ensure_every = ensure_every
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._counts = {"dropped": 0, "sent": 0, "send_failures": 0}

    # -- called from the user's threads ---------------------------------------------------
    def submit(self, record: dict[str, Any]) -> None:
        if len(self._queue) == self._queue.maxlen:
            self._counts["dropped"] += 1  # the deque discards the oldest entry on append
        self._queue.append(record)
        self._wake.set()

    def queue_len(self) -> int:
        return len(self._queue)

    def stats(self) -> dict[str, int]:
        return {**wrappers.stats(), **self._counts}

    # -- lifecycle ------------------------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="driftwatch-capture", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)

    # -- the sender thread ----------------------------------------------------------------
    def _hello(self) -> dict[str, Any]:
        return {
            "type": "hello",
            "pid": os.getpid(),
            "python": "%d.%d.%d" % sys.version_info[:3],
            "project_id": self._project_id,
            "sdks": wrappers.sdk_status(),
        }

    def _run(self) -> None:
        from driftwatch_llm.agent import ipc, launcher  # deferred: heavier than anything on the app's hot path

        link = ipc.IpcClient(self._home, io_timeout=1.0)
        announced: str | None = None  # the hello the agent last accepted, as JSON
        next_heartbeat = 0.0
        next_ensure = 0.0
        while not self._stop.is_set():
            self._wake.wait(timeout=1.0)
            self._wake.clear()
            try:
                now = time.monotonic()
                hello = self._hello()
                snapshot = json.dumps(hello, sort_keys=True)
                if announced != snapshot:
                    if link.send(hello) is not None:
                        announced = snapshot
                    elif link.last_error == "unavailable" and now >= next_ensure:
                        next_ensure = now + self._ensure_every
                        launcher.ensure_agent(self._home)  # may take seconds; this is not the app's thread
                        continue
                if announced is not None:
                    while self._queue and not self._stop.is_set():
                        record = self._queue.popleft()
                        if link.send({"type": "capture", "project_id": self._project_id, **record}) is None:
                            self._counts["send_failures"] += 1  # this record is lost; reconnect on the next pass
                            announced = None
                            break
                        self._counts["sent"] += 1
                    if announced is not None and now >= next_heartbeat:
                        next_heartbeat = now + self._heartbeat_every
                        if link.send({"type": "heartbeat", "pid": os.getpid(), "stats": self.stats()}) is None:
                            announced = None  # the agent is gone or restarted: say hello again (and start one if needed)
            except Exception:  # noqa: BLE001 - the sender thread must never die or raise
                wrappers._stats["errors"] += 1
        link.close()
