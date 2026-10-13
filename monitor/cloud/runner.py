"""The scheduled cloud runner: `python -m monitor.cloud.runner` (run by .github/workflows/cloud-runner.yml).

One pass: claim the jobs that are due, and for each one
  1. open the user's sealed provider key with the runner's private key (in memory only),
  2. ask the project's fixed probes (temperature 0) and re-ask the first one twice at temperature 0.7,
  3. score canary accuracy (known answers), self-consistency (how much the sampled answers disagree) and embedding
     drift of the probe answers against a baseline built from the first runs, using the same math as everywhere,
  4. write only numbers, then finish the job with one of a few fixed outcomes.

Rules this module keeps (GitHub Actions logs are public on a public repository):
- It prints one line per job (a short id, an outcome word, counts) and one summary line. It never prints a probe, an
  answer, a provider message, a key or an exception message.
- On GitHub it registers the opened key with `::add-mask::` before using it, so even an accident cannot show it.
- Every failure is reduced to a fixed outcome; no partial signals are written; the key and the answers are dropped
  with the job.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

import httpx
import numpy as np

from driftwatch_llm.core.canary import score_answer
from driftwatch_llm.core.consistency import self_consistency_disagreement
from driftwatch_llm.core.embedding import embedding_drift_score_fast, make_embedder
from driftwatch_llm.core.scoring import ScoringConfig, combine_signals
from monitor.cloud import seal
from monitor.cloud.providers import BadReply, ProviderAuthError, ProviderError
from monitor.cloud.providers import complete as provider_complete

SYSTEM_PROMPT = "You are a careful assistant. Follow the instruction exactly and keep the answer short."
SAMPLED_TEMPERATURE = 0.7
EXTRA_SAMPLES = 2  # the first probe is re-asked this many times at SAMPLED_TEMPERATURE
BASELINE_RUNS = 3  # the first successful runs build the reference; drift is measured from the next run on
MAX_VECTORS = 15  # per stored set; bounds what the database holds


class RunnerApiError(Exception):
    """A call to the database API failed. The message is a fixed sentence."""


class RunnerApi:
    """The database functions the runner may call, through the public API with the runner secret."""

    def __init__(self, base_url: str, anon_key: str, runner_secret: str, transport: httpx.BaseTransport | None = None) -> None:
        self._secret = runner_secret
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"), headers={"apikey": anon_key, "content-type": "application/json"}, timeout=30.0, transport=transport
        )

    def _call(self, fn: str, **args: Any) -> Any:
        try:
            r = self._client.post(f"/rest/v1/rpc/{fn}", json={"p_secret": self._secret, **args})
        except httpx.HTTPError:
            raise RunnerApiError("the database could not be reached") from None
        if r.status_code >= 400:
            raise RunnerApiError(f"the database refused {fn}")
        try:
            return r.json() if r.content else None
        except ValueError:
            raise RunnerApiError("the database answered with something unreadable") from None

    def claim(self) -> list[dict[str, Any]]:
        return self._call("runner_claim_jobs") or []

    def get_secret(self, model_id: str, lease: str) -> dict[str, Any]:
        return self._call("runner_get_secret", p_model_id=model_id, p_lease=lease)

    def get_vectors(self, model_id: str, lease: str) -> dict[str, Any]:
        return self._call("runner_get_vectors", p_model_id=model_id, p_lease=lease)

    def save_vectors(self, model_id: str, lease: str, baseline: str, recent: str, runs: int) -> None:
        self._call("runner_save_vectors", p_model_id=model_id, p_lease=lease, p_baseline=baseline, p_recent=recent, p_runs=runs)

    def write_signals(self, model_id: str, lease: str, events: list[dict[str, Any]]) -> int:
        return int(self._call("runner_write_signals", p_model_id=model_id, p_lease=lease, p_events=events) or 0)

    def finish(self, model_id: str, lease: str, outcome: str, calls: int) -> None:
        self._call("runner_finish_job", p_model_id=model_id, p_lease=lease, p_outcome=outcome, p_calls=calls)


class _Failure(Exception):
    def __init__(self, outcome: str, calls: int = 0) -> None:
        super().__init__(outcome)
        self.outcome = outcome
        self.calls = calls


def _pack(vectors: np.ndarray) -> str:
    return base64.b64encode(np.asarray(vectors, dtype=np.float32).tobytes()).decode()


def _unpack(raw: Any, dim: int) -> np.ndarray:
    if not raw:
        return np.zeros((0, dim), dtype=np.float32)
    data = base64.b64decode(str(raw).replace("\n", ""))
    if len(data) % (4 * dim) != 0:  # a different embedding model than before: start the reference again
        return np.zeros((0, dim), dtype=np.float32)
    return np.frombuffer(data, dtype=np.float32).reshape(-1, dim).copy()


class Runner:
    def __init__(
        self,
        api: Any,
        private_key: str | dict[int, str],
        embedder: Any,
        complete: Callable[..., str] = provider_complete,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._api = api
        # one private key (key id 1) or several by key id: during a rotation the old and the new are both held
        self._privates: dict[int, str] = {1: private_key} if isinstance(private_key, str) else dict(private_key)
        self._embedder = embedder
        self._complete = complete
        self._now = now

    def run_once(self) -> dict[str, int]:
        summary = {"jobs": 0, "ok": 0, "failed": 0}
        for job in self._api.claim():
            summary["jobs"] += 1
            outcome, calls, signals = self._run_job(job)
            try:
                self._api.finish(job["model_id"], job["lease"], outcome, calls)
            except Exception:  # noqa: BLE001 - the lease will expire and the job will be retried
                outcome = "finish_failed"
            summary["ok" if outcome == "ok" else "failed"] += 1
            print(f"job {str(job.get('model_id', ''))[:8]} outcome={outcome} calls={calls} signals={signals}", flush=True)
        print(f"runner jobs={summary['jobs']} ok={summary['ok']} failed={summary['failed']}", flush=True)
        return summary

    # -- one job ------------------------------------------------------------------------------------------------
    def _run_job(self, job: dict[str, Any]) -> tuple[str, int, int]:
        calls = 0
        try:
            model_id, lease = job["model_id"], job["lease"]
            probes = self._check_probes(job.get("probes"))
            max_calls = int(job.get("max_calls", 0))
            if len(probes) + EXTRA_SAMPLES > max_calls:
                raise _Failure("runner_error")
            try:
                box = self._api.get_secret(model_id, lease)
                private = self._privates.get(box.get("key_id")) if isinstance(box, dict) else None
                if private is None:  # sealed under a key id this runner no longer (or does not yet) hold
                    raise _Failure("runner_error")
                key = seal.open_sealed(private, model_id, box)
            except seal.SealError:
                raise _Failure("runner_error") from None
            if os.environ.get("GITHUB_ACTIONS") == "true":
                print(f"::add-mask::{key}", flush=True)  # a runner command, not output: registered before any use
            answers, samples, calls = self._ask(job, key, probes)
            events = self._score(job, probes, answers, samples, model_id, lease)
            self._api.write_signals(model_id, lease, events)
            return "ok", calls, len(events)
        except _Failure as f:
            return f.outcome, max(calls, f.calls), 0
        except Exception:  # noqa: BLE001 - never let anything (and never its message) escape
            return "runner_error", calls, 0

    @staticmethod
    def _check_probes(probes: Any) -> list[dict[str, Any]]:
        if not isinstance(probes, list) or not 1 <= len(probes) <= 5:
            raise _Failure("runner_error")
        clean = []
        for p in probes:
            if not isinstance(p, dict) or p.get("match_type") not in ("contains", "exact"):
                raise _Failure("runner_error")
            if not all(isinstance(p.get(k), str) and p[k] for k in ("prompt", "expected")):
                raise _Failure("runner_error")
            clean.append(p)
        return sorted(clean, key=lambda p: p.get("position", 0))

    def _ask(self, job: dict[str, Any], key: str, probes: list[dict[str, Any]]) -> tuple[list[str], list[str], int]:
        calls = 0
        provider, model = job["provider"], job["model"]
        answers: list[str] = []
        samples: list[str] = []
        try:
            for p in probes:
                answers.append(self._complete(provider, key, model, SYSTEM_PROMPT, p["prompt"], temperature=0.0))
                calls += 1  # counted when the provider answered: a refused or failed call costs the user nothing
            samples.append(answers[0])
            for _ in range(EXTRA_SAMPLES):
                samples.append(self._complete(provider, key, model, SYSTEM_PROMPT, probes[0]["prompt"], temperature=SAMPLED_TEMPERATURE))
                calls += 1
        except ProviderAuthError:
            raise _Failure("provider_auth", calls) from None
        except BadReply:
            raise _Failure("bad_reply", calls) from None
        except ProviderError:
            raise _Failure("provider_error", calls) from None
        return answers, samples, calls

    def _score(self, job, probes, answers, samples, model_id, lease) -> list[dict[str, Any]]:
        canary = sum(score_answer(a, p["expected"], p["match_type"]) for a, p in zip(answers, probes)) / len(probes)
        vectors = np.asarray(self._embedder.encode(answers + samples), dtype=np.float32)
        answer_vecs, sample_vecs = vectors[: len(answers)], vectors[len(answers):]
        consistency = self_consistency_disagreement(sample_vecs)
        dim = vectors.shape[1]
        state = self._api.get_vectors(model_id, lease) or {}
        baseline = _unpack(state.get("baseline"), dim)
        recent = _unpack(state.get("recent"), dim)
        runs = int(state.get("runs") or 0)
        drift: float | None = None
        if runs < BASELINE_RUNS or len(baseline) == 0:
            baseline = np.vstack([baseline, answer_vecs])[-MAX_VECTORS:]
            recent = answer_vecs
        else:
            recent = np.vstack([recent, answer_vecs])[-MAX_VECTORS:]
            drift = embedding_drift_score_fast(baseline, recent)
        present = {"canary_accuracy": canary, "self_consistency": consistency}
        if drift is not None:
            present["embedding_drift"] = drift
        combined = combine_signals(present, ScoringConfig())
        stamp = self._now().isoformat()
        base_meta = {"provider": job["provider"], "model": job["model"], "probes": len(probes), "runs": runs + 1}
        events = [
            {"event_id": str(uuid.uuid4()), "signal": name, "value": float(value), "occurred_at": stamp, "meta": dict(base_meta)}
            for name, value in present.items()
        ]
        events.append(
            {"event_id": str(uuid.uuid4()), "signal": "combined_score", "value": float(combined.score), "occurred_at": stamp,
             "meta": {**base_meta, "signals": sorted(present)}}
        )
        self._api.save_vectors(model_id, lease, _pack(baseline), _pack(recent), runs + 1)
        return events


def _private_keys(env: dict[str, str]) -> dict[int, str] | None:
    """RUNNER_PRIVATE_KEYS (a JSON map of key id to key, used during a rotation) or RUNNER_PRIVATE_KEY (key id 1)."""
    raw = env.get("RUNNER_PRIVATE_KEYS")
    if raw:
        try:
            parsed = json.loads(raw)
            keys = {int(k): v for k, v in parsed.items()}
        except (ValueError, TypeError, AttributeError):
            return None
        return keys if keys and all(isinstance(v, str) and v for v in keys.values()) else None
    single = env.get("RUNNER_PRIVATE_KEY")
    return {1: single} if single else None


def main(env: dict[str, str] | None = None) -> int:
    env = dict(os.environ) if env is None else env
    privates = _private_keys(env)
    if privates is None or any(not env.get(k) for k in ("SUPABASE_URL", "SUPABASE_ANON_KEY", "RUNNER_SECRET")):
        print("runner: missing settings", flush=True)
        return 2
    api = RunnerApi(env["SUPABASE_URL"], env["SUPABASE_ANON_KEY"], env["RUNNER_SECRET"])
    try:
        runner = Runner(api, privates, embedder=make_embedder("onnx"), complete=provider_complete)
        summary = runner.run_once()
    except RunnerApiError as exc:
        print(f"runner: {exc}", flush=True)
        return 1
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
