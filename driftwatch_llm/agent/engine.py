"""Turns captured LLM responses into drift events, locally.

Per project the engine keeps a baseline (the first N responses, frozen, stored as embedding vectors only)
and a rolling window of the latest responses. When enough new responses have arrived it measures how far
the window has moved from the baseline (the same MMD the server uses) and emits two events:
`embedding_drift` and `combined_score`.

Only measured signals are emitted. With one signal the unchanged `combine_signals` returns that signal's
contribution, labelled `mode = "embedding_only"`; no `alert` is set because the alert threshold was tuned
for five signals (decision D-021). Response text is embedded and dropped: it is never stored.
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

import numpy as np

from driftwatch_llm import __version__
from driftwatch_llm.agent.store import AgentStore
from driftwatch_llm.core.embedding import embedding_drift_score_fast
from driftwatch_llm.core.events import IngestionError, validate_event
from driftwatch_llm.core.scoring import ScoringConfig, combine_signals

DEFAULT_BASELINE_SIZE = 200
MIN_BASELINE = 30
WINDOW_SIZE = 20
MIN_NEW_RESPONSES = 5
MIN_INTERVAL_SECONDS = 60.0
MAX_CHARS = 8000
BACKLOG_SIZE = 200  # responses held while the model loads
EMBEDDER_NAME = "minilm-l6-v2"
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]+")


@dataclass
class _Project:
    collecting: list[np.ndarray] = field(default_factory=list)
    baseline: np.ndarray | None = None
    window: deque = field(default_factory=lambda: deque(maxlen=WINDOW_SIZE))
    models: deque = field(default_factory=lambda: deque(maxlen=WINDOW_SIZE))
    new_since_emit: int = 0
    last_emit: float = 0.0


def _model_label(model: Any) -> str:
    if not isinstance(model, str):
        return "unknown"
    return _CONTROL.sub(" ", model).strip()[:64] or "unknown"


class Engine:
    def __init__(
        self,
        store: AgentStore,
        embedder: Any | None,
        clock: Callable[[], float] = time.time,
        baseline_size: int = DEFAULT_BASELINE_SIZE,
        min_baseline: int = MIN_BASELINE,
        window_size: int = WINDOW_SIZE,
        min_new: int = MIN_NEW_RESPONSES,
        min_interval: float = MIN_INTERVAL_SECONDS,
        max_chars: int = MAX_CHARS,
        backlog_size: int = BACKLOG_SIZE,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._clock = clock
        self._baseline_size = baseline_size
        self._min_baseline = min_baseline
        self._window_size = window_size
        self._min_new = min_new
        self._min_interval = min_interval
        self._max_chars = max_chars
        self._lock = threading.RLock()
        self._projects: dict[str, _Project] = {}
        # Responses that arrive while the model is still loading wait here, in memory only (never on disk), and are
        # processed in order once it is ready. Bounded: the oldest are dropped (and counted) beyond backlog_size.
        self._backlog: deque[tuple[str, str, str | None]] = deque()
        self._backlog_size = backlog_size

    # -- embedder -----------------------------------------------------------------------
    def set_embedder(self, embedder: Any) -> None:
        with self._lock:
            self._embedder = embedder
            pending, self._backlog = list(self._backlog), deque()
            for project_id, text, model in pending:
                self._process(project_id, text, model)

    @property
    def embedder_ready(self) -> bool:
        return self._embedder is not None

    # -- state --------------------------------------------------------------------------
    def _project(self, project_id: str) -> _Project:
        proj = self._projects.get(project_id)
        if proj is None:
            proj = _Project(
                window=deque(maxlen=self._window_size), models=deque(maxlen=self._window_size)
            )
            proj.baseline = self._store.load_baseline(project_id)
            self._projects[project_id] = proj
        return proj

    def baseline_status(self, project_id: str) -> dict[str, Any]:
        with self._lock:
            proj = self._project(project_id)
            frozen = proj.baseline is not None
            return {
                "frozen": frozen,
                "collected": len(proj.baseline) if frozen else len(proj.collecting),
                "target": self._baseline_size,
                "window": len(proj.window),
            }

    def projects(self) -> list[str]:
        with self._lock:
            return sorted(self._projects)

    def _freeze_locked(self, project_id: str, proj: _Project) -> None:
        proj.baseline = np.stack(proj.collecting).astype(np.float32)
        proj.collecting = []
        proj.window.clear()
        proj.models.clear()
        proj.new_since_emit = 0
        self._store.save_baseline(project_id, proj.baseline)

    def freeze(self, project_id: str) -> bool:
        """Freeze the baseline now if enough responses were collected. True when frozen."""
        with self._lock:
            proj = self._project(project_id)
            if proj.baseline is not None:
                return True
            if len(proj.collecting) < self._min_baseline:
                return False
            self._freeze_locked(project_id, proj)
            return True

    def reset(self, project_id: str) -> None:
        with self._lock:
            self._projects.pop(project_id, None)
            self._store.clear_baseline(project_id)

    # -- capture ------------------------------------------------------------------------
    def _embed(self, text: str) -> np.ndarray | None:
        try:
            out = np.asarray(self._embedder.encode([text]), dtype=np.float32)
            vec = out[0]
            if vec.ndim != 1 or not np.all(np.isfinite(vec)):
                raise ValueError("bad embedding")
            return vec
        except Exception:  # noqa: BLE001 - one bad response must not stop the agent
            self._store.bump("embed_errors")
            return None

    def capture(
        self, project_id: str, text: Any, provider: str | None = None, model: str | None = None
    ) -> list[dict[str, Any]]:
        """Take one response. Returns the events it produced (also stored and queued for sync)."""
        if not isinstance(text, str) or not text.strip():
            self._store.bump("ignored_empty")
            return []
        text = text[: self._max_chars]
        with self._lock:
            if self._embedder is None:
                if len(self._backlog) >= self._backlog_size:
                    self._backlog.popleft()
                    self._store.bump("dropped_no_embedder")
                self._backlog.append((project_id, text, model))
                self._store.bump("buffered_while_loading")
                return []
            return self._process(project_id, text, model)

    def _process(self, project_id: str, text: str, model: str | None) -> list[dict[str, Any]]:
        with self._lock:
            proj = self._project(project_id)
            vec = self._embed(text)
            if vec is None:
                return []
            if proj.baseline is None:
                proj.collecting.append(vec)
                if len(proj.collecting) >= self._baseline_size:
                    self._freeze_locked(project_id, proj)
                return []
            proj.window.append(vec)
            proj.models.append(_model_label(model))
            proj.new_since_emit += 1
            now = self._clock()
            if (
                len(proj.window) < self._min_new
                or proj.new_since_emit < self._min_new
                or now - proj.last_emit < self._min_interval
            ):
                return []
            events = self._emit(project_id, proj, now)
            proj.new_since_emit = 0
            proj.last_emit = now
            return events

    def _emit(self, project_id: str, proj: _Project, now: float) -> list[dict[str, Any]]:
        assert proj.baseline is not None
        score = embedding_drift_score_fast(proj.baseline, np.stack(list(proj.window)))
        combined = combine_signals({"embedding_drift": score}, ScoringConfig())
        models = dict(Counter(proj.models).most_common(5))
        stamp = datetime.fromtimestamp(now, timezone.utc).isoformat()
        specs = [
            (
                "embedding_drift",
                score,
                {
                    "baseline_n": len(proj.baseline),
                    "current_n": len(proj.window),
                    # Early values (small window) are noisier: measured floor 0.06 mean / 0.12-0.18 worst at
                    # windows of 5-10 versus 0.03 / 0.08 at 20 (scripts/measure_embedding_only.py).
                    "window_full": len(proj.window) >= self._window_size,
                    "embedder": EMBEDDER_NAME,
                    "models": models,
                    "agent_version": __version__,
                },
            ),
            (
                "combined_score",
                combined.score,
                {
                    "mode": "embedding_only",
                    "signals": ["embedding_drift"],
                    "triggering_signals": combined.triggering_signals,
                    "agent_version": __version__,
                },
            ),
        ]
        events: list[dict[str, Any]] = []
        for signal, value, meta in specs:
            event = {
                "schema_version": 1,
                "event_id": str(uuid.uuid4()),
                "occurred_at": stamp,
                "source": "agent",
                "signal": signal,
                "value": float(value),
                "meta": meta,
                "content_capture": False,
            }
            try:
                validate_event(event)
            except IngestionError:
                self._store.bump("invalid_events")
                continue
            self._store.add_signal(project_id, signal, float(value), meta, ts=now)
            self._store.enqueue(project_id, event)
            events.append(event)
        self._store.bump("emitted", len(events))
        return events
