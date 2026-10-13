"""The agent's judge: grades a small, redacted sample of captured responses and turns the scores into a trend signal.

Everything about it is opt-in and bounded:

- Off unless `driftwatch judge enable` was run (settings in judge.json; a damaged file reads as off).
- One response in `sample_every`, at most `max_per_day` a day, and only once a baseline exists.
- The text is masked and cut (`core.redact.prepare_for_judge`) the moment it is offered, held in memory in a
  bounded queue, and never written anywhere. What is sent: the redacted text, and with the free allowance an
  idempotency key. Prompts are never read, so the grading is answer-only.
- The credential is the one the user chose. The free allowance goes through the relay with the project key; an own
  key goes straight to its provider and the project key never leaves for a provider. If the chosen credential stops
  working the judge parks with a plain sentence; it never falls back to a different credential by itself.
- Every five new scores, one `judge_trend` event (the mean of the last ten scores) joins the outbox like any other.
- Nothing a server says is kept: only fixed sentences reach status and logs.
"""
from __future__ import annotations

import hashlib
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx

from driftwatch_llm import paths
from driftwatch_llm.core.judge import JUDGE_SYSTEM, build_prompt, parse_score
from driftwatch_llm.core.redact import prepare_for_judge
from driftwatch_llm.endpoints import Endpoints
from driftwatch_llm.judge_settings import JudgeSettings, read_settings

QUEUE_MAX = 20
WINDOW = 10  # scores averaged into one trend value
EMIT_EVERY = 5  # new scores between trend events
RETRY_DELAYS = (5.0, 30.0)  # after the 1st and 2nd failed attempt; a 3rd failure drops the sample
PARK_RETRY_SECONDS = 3600.0  # a spent allowance or a switched-off relay is checked again after an hour
RELAY_TIMEOUT = 60.0  # the free relay may be waking from sleep
OWN_TIMEOUT = 30.0

_BASES = {"groq": "https://api.groq.com/openai/v1", "openai": "https://api.openai.com/v1"}
_DEFAULT_MODELS = {"groq": "qwen/qwen3.8-27b", "openai": "gpt-4o-mini"}

_ERR_NETWORK = "the judge service could not be reached"
_ERR_SERVER = "the judge service had a problem"
_ERR_REPLY = "the judge gave an unusable answer"


class JudgeWorker:
    def __init__(
        self,
        store: Any,
        engine: Any,
        home: Path | str | None,
        secrets: Any,
        provider_keys: Any,
        endpoints: Endpoints,
        clock: Callable[[], float] = time.time,
        transport: httpx.BaseTransport | None = None,
        settings_ttl: float = 5.0,
    ) -> None:
        self._store = store
        self._engine = engine
        self._home = Path(home) if home is not None else paths.config_dir()
        self._secrets = secrets
        self._keys = provider_keys
        self._ep = endpoints
        self._clock = clock
        self._transport = transport
        self._ttl = settings_ttl
        self._lock = threading.RLock()
        self._settings = JudgeSettings()
        self._settings_at = float("-inf")
        self._queue: deque[dict[str, Any]] = deque()
        self._seen: dict[str, int] = {}
        self._scores: dict[str, deque[float]] = {}
        self._new: dict[str, int] = {}
        self._parked: dict[str, Any] | None = None
        self._last_error: str | None = None
        self._allowance: dict[str, int] | None = None

    # -- settings ----------------------------------------------------------------------
    def _current(self) -> JudgeSettings:
        now = self._clock()
        if now - self._settings_at >= self._ttl:
            self._settings = read_settings(self._home)
            self._settings_at = now
        return self._settings

    def _day(self) -> str:
        return datetime.fromtimestamp(self._clock(), timezone.utc).strftime("%Y%m%d")

    def _scored_today(self) -> int:
        return self._store.counter(f"judge_day_{self._day()}")

    # -- credentials -------------------------------------------------------------------
    def _credential(self, project_id: str, s: JudgeSettings) -> tuple[str | None, str]:
        """(secret or None, a fingerprint that changes when the setup changes)."""
        if s.credential == "free":
            found = self._secrets.load(project_id)
            secret = found[0] if found else None
        else:
            found = self._keys.load(s.provider)
            secret = found[0] if found else None
        digest = hashlib.sha256(secret.encode()).hexdigest()[:16] if secret else "none"
        return secret, f"{s.credential}|{s.provider}|{s.model}|{s.base_url}|{digest}"

    def _park(self, reason: str, fingerprint: str, retry_after: float | None = None) -> None:
        self._parked = {"reason": reason, "fingerprint": fingerprint, "until": self._clock() + retry_after if retry_after else None}
        self._queue.clear()

    def _unpark_if_changed(self, project_id: str, s: JudgeSettings) -> None:
        if self._parked is None:
            return
        _, fingerprint = self._credential(project_id, s)
        until = self._parked["until"]
        if fingerprint != self._parked["fingerprint"] or (until is not None and self._clock() >= until):
            self._parked = None

    # -- offering ----------------------------------------------------------------------
    def offer(self, project_id: str, text: Any, model: Any = None) -> None:
        with self._lock:
            s = self._current()
            if not s.enabled:
                return
            self._unpark_if_changed(project_id, s)
            if self._parked is not None:
                return
            if not self._engine.baseline_status(project_id)["frozen"]:
                return
            count = self._seen.get(project_id, 0) + 1
            self._seen[project_id] = count
            if count % s.sample_every != 0:
                return
            if self._scored_today() + len(self._queue) >= s.max_per_day:
                self._store.bump("judge_skipped_cap")
                return
            prepared = prepare_for_judge(text)
            if not prepared:
                self._store.bump("judge_skipped_empty")
                return
            if len(self._queue) >= QUEUE_MAX:
                self._queue.popleft()
                self._store.bump("judge_dropped_queue")
            self._queue.append({"project": project_id, "text": prepared, "attempts": 0, "due": 0.0})

    # -- processing --------------------------------------------------------------------
    def process_one(self) -> str | None:
        """Handle the next sample: "scored", "retry", "dropped", "parked", "waiting", or None when there is nothing to do."""
        with self._lock:
            s = self._current()
            if not s.enabled or not self._queue:
                return None
            item = self._queue[0]
            if item["due"] > self._clock():
                return "waiting"
            self._queue.popleft()
        return self._attempt(item, s)

    def _attempt(self, item: dict[str, Any], s: JudgeSettings) -> str:
        project = item["project"]
        secret, fingerprint = self._credential(project, s)
        if secret is None:
            with self._lock:
                if s.credential == "free":
                    self._park("no project key on this machine (run `driftwatch login`)", fingerprint)
                else:
                    self._park(f"no {s.provider} key stored (run `driftwatch key set {s.provider}`)", fingerprint)
            return "parked"
        try:
            request = self._build_request(s, secret, item["text"])
        except ValueError as exc:
            with self._lock:
                self._park(str(exc), fingerprint)
            return "parked"
        url, headers, body, timeout = request
        try:
            with httpx.Client(transport=self._transport, timeout=timeout, follow_redirects=False) as client:
                response = client.post(url, headers=headers, json=body)
        except httpx.HTTPError:
            return self._transient(item, _ERR_NETWORK)
        return self._handle(item, s, fingerprint, response)

    def _build_request(self, s: JudgeSettings, secret: str, text: str) -> tuple[str, dict[str, str], dict[str, Any], float]:
        if s.credential == "free":
            url = self._ep.relay_url.rstrip("/") + "/v1/judge"
            return url, {"Authorization": f"Bearer {secret}"}, {"text": text, "idempotency_key": str(uuid.uuid4())}, RELAY_TIMEOUT
        base = s.base_url if s.provider == "openai-compatible" else _BASES[s.provider]
        model = s.model or _DEFAULT_MODELS.get(s.provider)
        if not base:
            raise ValueError("no server address set (run `driftwatch judge enable --own --provider openai-compatible --base-url ...`)")
        if not model:
            raise ValueError("no model set (run `driftwatch judge enable --own --model NAME`)")
        body = {
            "model": model,
            "messages": [{"role": "system", "content": JUDGE_SYSTEM}, {"role": "user", "content": build_prompt(text)}],
            "max_tokens": 4,
            "temperature": 0,
        }
        return base.rstrip("/") + "/chat/completions", {"Authorization": f"Bearer {secret}"}, body, OWN_TIMEOUT

    def _handle(self, item: dict[str, Any], s: JudgeSettings, fingerprint: str, response: httpx.Response) -> str:
        status = response.status_code
        if status == 200:
            try:
                data = response.json()
                if s.credential == "free":
                    score = float(data["score"])
                    if not 0.0 <= score <= 1.0:
                        raise ValueError
                    remaining = data.get("remaining")
                    if isinstance(remaining, int) and not isinstance(remaining, bool):
                        self._allowance = {"remaining": remaining}
                else:
                    score = parse_score(data["choices"][0]["message"]["content"])
            except (ValueError, KeyError, IndexError, TypeError):
                return self._transient(item, _ERR_REPLY)
            return self._record(item["project"], score, s)
        detail = ""
        try:
            raw = response.json()
            detail = str(raw.get("detail", "")) if isinstance(raw, dict) else ""
        except ValueError:
            pass
        with self._lock:
            if status == 403 and s.credential == "free":
                self._park("verify your email address to use the free allowance", fingerprint)
                return "parked"
            if status in (401, 403):
                who = "the project key was rejected (run `driftwatch login`)" if s.credential == "free" else (
                    f"the {s.provider} key was rejected (run `driftwatch key set {s.provider}`)"
                )
                self._park(who, fingerprint)
                return "parked"
            if status == 429 and s.credential == "free" and "allowance" in detail.lower():
                self._park(
                    "free allowance used. Add your own key: driftwatch key set groq, then driftwatch judge enable --own",
                    fingerprint,
                    PARK_RETRY_SECONDS,
                )
                return "parked"
            if status == 409:
                return self._drop(item, None)
        return self._transient(item, _ERR_SERVER)

    def _transient(self, item: dict[str, Any], sentence: str) -> str:
        with self._lock:
            self._last_error = sentence
            item["attempts"] += 1
            if item["attempts"] > len(RETRY_DELAYS):
                return self._drop(item, sentence)
            item["due"] = self._clock() + RETRY_DELAYS[item["attempts"] - 1]
            self._queue.appendleft(item)
            return "retry"

    def _drop(self, item: dict[str, Any], sentence: str | None) -> str:
        self._store.bump("judge_failed")
        return "dropped"

    def _record(self, project_id: str, score: float, s: JudgeSettings) -> str:
        with self._lock:
            self._last_error = None
            self._store.bump("judge_scored")
            self._store.bump(f"judge_day_{self._day()}")
            window = self._scores.setdefault(project_id, deque(maxlen=WINDOW))
            window.append(score)
            self._new[project_id] = self._new.get(project_id, 0) + 1
            if self._new[project_id] >= EMIT_EVERY:
                self._new[project_id] = 0
                self._engine.emit_signal(
                    project_id,
                    "judge_trend",
                    sum(window) / len(window),
                    {"mode": "judge_answer_only", "credential": s.credential, "n": len(window)},
                )
        return "scored"

    # -- views -------------------------------------------------------------------------
    def latest(self, project_id: str) -> dict[str, float]:
        """The newest judge trend value from the last day, for the combined score."""
        rows = self._store.recent_signals(project_id, "judge_trend", 1)
        if rows and rows[0]["ts"] >= self._clock() - 86400:
            return {"judge_trend": float(rows[0]["value"])}
        return {}

    def status(self) -> dict[str, Any]:
        with self._lock:
            s = self._current()
            if not s.enabled:
                state = "off"
            elif self._parked is not None:
                state = f"parked: {self._parked['reason']}"
            else:
                state = "idle"
            return {
                "enabled": s.enabled,
                "credential": s.credential,
                "provider": s.provider if s.credential == "own" else None,
                "state": state,
                "queued": len(self._queue),
                "scored_today": self._scored_today(),
                "max_per_day": s.max_per_day,
                "sample_every": s.sample_every,
                "last_error": self._last_error,
                "allowance": dict(self._allowance) if self._allowance else None,
            }

