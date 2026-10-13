"""The agent process: store, engine, sync worker and IPC server tied together.

Lifetime: the agent exits `linger` seconds after the last heartbeat from any client (clients send one every
5 seconds), or on a `stop` message. It never makes LLM calls and never reads or stores prompts.
"""

from __future__ import annotations

import os
from collections import deque
import threading
import time
from pathlib import Path
from typing import Any, Callable

from driftwatch_llm import __version__, paths
from driftwatch_llm.agent import ipc
from driftwatch_llm.agent.engine import DEFAULT_BASELINE_SIZE, MIN_BASELINE, MIN_INTERVAL_SECONDS, Engine
from driftwatch_llm.agent.store import AgentStore
from driftwatch_llm.agent.sync import SyncWorker
from driftwatch_llm.api import Api
from driftwatch_llm.endpoints import resolve
from driftwatch_llm.secrets import SecretStore

ALIVE_WINDOW = 15.0  # a client counts as connected for this long after its last message
PRUNE_EVERY = 3600.0
LOAD_TIMEOUT = 900.0  # a model still not loaded after this long is reported as failed (it may yet finish)
CAPTURE_QUEUE = 1000  # responses waiting to be scored; the oldest are dropped (and counted) beyond this


def _default_embedder() -> Any:
    from driftwatch_llm.core import embedding

    # "onnx" (fastembed, the [agent] extra) by default. DRIFTWATCH_AGENT_EMBEDDER=sentence-transformers uses an
    # installed torch/sentence-transformers instead: the same model, handy where that is already installed.
    kind = os.environ.get("DRIFTWATCH_AGENT_EMBEDDER", "onnx")
    try:
        return embedding.make_embedder(kind, local_only=True)  # a cached model loads without any network check
    except Exception:  # noqa: BLE001 - not cached yet (or unreadable): fall back to the normal, downloading load
        return embedding.make_embedder(kind)


def _embedder_label() -> str:
    """What events say produced them: the test embedder must never be mistaken for the real model."""
    return "hash" if os.environ.get("DRIFTWATCH_AGENT_EMBEDDER") == "hash" else "minilm-l6-v2"


class AgentRuntime:
    def __init__(
        self,
        home: Path | str | None = None,
        embedder_factory: Callable[[], Any] | None = _default_embedder,
        api: Api | None = None,
        secrets: Any | None = None,
        clock: Callable[[], float] = time.time,
        baseline_size: int = DEFAULT_BASELINE_SIZE,
        min_baseline: int = MIN_BASELINE,
        min_interval: float = MIN_INTERVAL_SECONDS,
        linger: float = 30.0,
        sync_interval: float = 10.0,
        capture_queue: int = CAPTURE_QUEUE,
        load_timeout: float = LOAD_TIMEOUT,
        embedder_name: str | None = None,
    ) -> None:
        self._home = Path(home) if home is not None else paths.config_dir()
        self._clock = clock
        self._linger = linger
        self._sync_interval = sync_interval
        self._factory = embedder_factory
        self._store = AgentStore(ipc.agent_dir(self._home) / "agent.sqlite3", clock=clock)
        self._engine = Engine(
            self._store, None, clock=clock, baseline_size=baseline_size, min_baseline=min_baseline, min_interval=min_interval,
            embedder_name=embedder_name or _embedder_label(),
        )
        self._load_timeout = load_timeout
        self._sync = SyncWorker(
            self._store,
            api if api is not None else Api(resolve(dev=os.environ.get("DRIFTWATCH_DEV") == "1")),
            secrets if secrets is not None else SecretStore(home=self._home),
            clock=clock,
        )
        self._server = ipc.IpcServer(self._home, self.handle)
        self._started = clock()
        self._clients: dict[int, dict[str, Any]] = {}
        self._clients_lock = threading.Lock()
        self._stop = threading.Event()
        self._embedder_state = "loading" if embedder_factory is not None else "skipped"
        self._embedder_started: float | None = None
        self._threads: list[threading.Thread] = []
        self._dashboard: Any = None
        # The IPC thread only queues; one worker embeds and scores, so a slow model never stalls a connection.
        self._queue: deque[tuple[str, str, str, str | None]] = deque()
        self._queue_max = capture_queue
        self._queue_lock = threading.Lock()
        self._work = threading.Event()

    # -- embedder -----------------------------------------------------------------------
    def load_embedder_now(self) -> None:
        if self._factory is None:
            return
        self._embedder_started = self._clock()
        try:
            self._engine.set_embedder(self._factory())
            self._embedder_state = "ready"
        except Exception as exc:  # noqa: BLE001 - report the class only: messages can carry paths
            self._embedder_state = f"failed: {type(exc).__name__}"

    # -- messages -----------------------------------------------------------------------
    def _touch(self, pid: int) -> dict[str, Any]:
        client = self._clients.setdefault(pid, {"python": "", "sdks": {}, "stats": {}})
        client["last_seen"] = self._clock()
        return client

    def handle(self, msg: dict[str, Any]) -> dict[str, Any]:
        kind = msg["type"]
        if kind == "hello":
            with self._clients_lock:
                client = self._touch(msg["pid"])
                client["python"] = msg.get("python", "")
                client["sdks"] = msg.get("sdks", {})
            return {"ok": True, "agent_version": __version__, "pid": os.getpid(), "protocol": ipc.PROTOCOL_VERSION}
        if kind == "heartbeat":
            with self._clients_lock:
                client = self._touch(msg["pid"])
                if "stats" in msg:
                    client["stats"] = msg["stats"]
            return {"ok": True}
        if kind == "capture":
            with self._queue_lock:
                if len(self._queue) >= self._queue_max:
                    self._queue.popleft()
                    self._store.bump("dropped_queue_full")
                self._queue.append((msg["project_id"], msg["text"], msg["provider"], msg.get("model")))
            self._work.set()
            return {"ok": True}
        if kind == "baseline":
            project = msg["project_id"]
            if msg["action"] == "freeze":
                return {"ok": True, "frozen": self._engine.freeze(project)}
            if msg["action"] == "reset":
                self._engine.reset(project)
                return {"ok": True}
            return {"ok": True, "baseline": self._engine.baseline_status(project)}
        if kind == "dashboard":
            port, token = self._dashboard_start()
            return {"ok": True, "port": port, "token": token}
        if kind == "stop":
            self._stop.set()
            return {"ok": True}
        return {"ok": True, "status": self._status()}

    # -- local dashboard ----------------------------------------------------------------
    def _dashboard_start(self) -> tuple[int, str]:
        with self._clients_lock:
            if self._dashboard is None:
                from driftwatch_llm.agent.dashboard import DashboardServer

                self._dashboard = DashboardServer(_DashboardView(self))
                self._dashboard.start()
            return self._dashboard.address[1], self._dashboard.token

    def _touch_viewer(self) -> None:
        with self._clients_lock:
            self._touch(-1)["python"] = "dashboard"  # keeps the agent alive while a page is open

    def _embedder_view(self, now: float) -> str:
        if (
            self._embedder_state == "loading"
            and self._embedder_started is not None
            and now - self._embedder_started > self._load_timeout
        ):
            return "failed: timeout"
        return self._embedder_state

    def _status(self) -> dict[str, Any]:
        now = self._clock()
        with self._clients_lock:
            clients = [
                {"pid": pid, "python": c["python"], "sdks": c["sdks"], "stats": c["stats"]}
                for pid, c in sorted(self._clients.items())
                if now - c["last_seen"] <= ALIVE_WINDOW
            ]
        parked = self._store.parked()
        projects = {
            pid: {
                "baseline": self._engine.baseline_status(pid),
                "pending": self._store.pending_count(pid),
                "parked": parked.get(pid),
            }
            for pid in self._engine.projects()
        }
        return {
            "agent_version": __version__,
            "protocol": ipc.PROTOCOL_VERSION,
            "pid": os.getpid(),
            "uptime_seconds": round(now - self._started, 1),
            "embedder": self._embedder_view(now),
            "embedder_loading_seconds": (
                round(now - self._embedder_started, 1)
                if self._embedder_state == "loading" and self._embedder_started is not None
                else None
            ),
            "clients": clients,
            "projects": projects,
            "sync": self._sync.status(),
            "queued": len(self._queue),
            "counters": self._store.counters(),
        }

    def drain(self) -> None:
        """Process everything queued, in the calling thread. The worker calls this; tests call it directly."""
        while True:
            with self._queue_lock:
                if not self._queue:
                    return
                project_id, text, provider, model = self._queue.popleft()
            try:
                self._engine.capture(project_id, text, provider, model)
                self._store.bump("captured")
            except Exception:  # noqa: BLE001 - one bad response must not stop the worker
                self._store.bump("capture_errors")

    def _worker(self) -> None:
        while not self._stop.is_set():
            self._work.wait(0.5)
            self._work.clear()
            self.drain()

    # -- lifetime -----------------------------------------------------------------------
    def tick(self) -> bool:
        """True when the agent should exit: asked to stop, or no client has spoken for `linger` seconds."""
        if self._stop.is_set():
            return True
        with self._clients_lock:
            last = max([self._started] + [c["last_seen"] for c in self._clients.values()])
        return self._clock() - last > self._linger

    def start(self) -> None:
        self._server.start()
        if self._factory is not None and self._embedder_state == "loading":
            self._spawn(self.load_embedder_now, "dw-embedder")
        self._spawn(self._sync_loop, "dw-sync")
        self._spawn(self._worker, "dw-worker")

    def _spawn(self, target: Callable[[], None], name: str) -> None:
        t = threading.Thread(target=target, name=name, daemon=True)
        t.start()
        self._threads.append(t)

    def _sync_loop(self) -> None:
        last_prune = time.monotonic()
        while not self._stop.wait(self._sync_interval):
            try:
                self._sync.drain_once()
                if time.monotonic() - last_prune > PRUNE_EVERY:
                    self._store.prune()
                    last_prune = time.monotonic()
            except Exception:  # noqa: BLE001 - a sync problem must not stop the agent
                self._store.bump("sync_errors")

    def shutdown(self) -> None:
        self._stop.set()
        if self._dashboard is not None:
            self._dashboard.stop()
        self._server.stop()
        for t in self._threads:
            t.join(timeout=2.0)
        self._store.close()


SERIES_SIGNALS = (
    "embedding_drift", "self_consistency", "canary_accuracy", "judge_trend", "hallucination_score", "combined_score",
)  # the names the website's charts use


class _DashboardView:
    """What the local dashboard may see: numbers and states, never response text (none is stored)."""

    def __init__(self, runtime: AgentRuntime) -> None:
        self._rt = runtime

    def touch(self) -> None:
        self._rt._touch_viewer()

    def projects(self) -> list[str]:
        return sorted(set(self._rt._store.projects()) | set(self._rt._engine.projects()))

    def series(self, project_id: str, range_name: str) -> dict[str, Any]:
        from datetime import datetime, timezone

        from driftwatch_llm.agent.dashboard import RANGES

        since = self._rt._clock() - RANGES[range_name]
        out: dict[str, Any] = {}
        for name in SERIES_SIGNALS:
            rows = self._rt._store.signals_since(project_id, name, since, limit=500)
            out[name] = [
                {"timestamp": datetime.fromtimestamp(r["ts"], timezone.utc).isoformat(), "value": r["value"]} for r in rows
            ]
        return out

    def status(self) -> dict[str, Any]:
        rt = self._rt
        sync = rt._sync.status()
        pending = rt._store.pending_count()
        parked = rt._store.parked()
        if parked:
            state = "paused"
        elif pending and sync.get("last_error"):
            state = "offline"
        elif pending:
            state = "pending"
        else:
            state = "synced"
        return {
            "sync": {
                "state": state,
                "pending": pending,
                "last_success_at": sync.get("last_success_at"),
                "last_error": sync.get("last_error"),
                "parked": parked,
            },
            "embedder": rt._embedder_view(rt._clock()),
            "baselines": {pid: rt._engine.baseline_status(pid) for pid in rt._engine.projects()},
            "agent_version": __version__,
        }
