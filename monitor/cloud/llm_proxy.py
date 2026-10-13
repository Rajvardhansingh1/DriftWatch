"""POST /v1/judge - the free allowance's relay.

A user without their own provider key can have a small sample of their app's responses graded through this route.
It is deliberately narrow:

- One typed operation. The body is `{"text": <string>, "idempotency_key": <uuid>}` and nothing else (extra fields are a
  422). The prompt is a fixed template on this server; the model, `max_tokens` and temperature are fixed here. A client
  system prompt, model name or URL cannot be sent, so there is nothing to redirect.
- Identity is the project API key (`Authorization: Bearer dw_...`). It is metered by the `reserve_quota` and
  `settle_quota` database functions (migration 0010), called with the public key, so this service holds no Supabase
  service key. One unit is reserved before the provider call and refunded when the call fails.
- The request text is never stored and never logged. Log lines carry a status code and a duration, nothing else, and
  provider errors are reduced to a fixed sentence before they leave this module.
- A reused idempotency key is a replay: it is answered 409 and the provider is NOT called, so a key cannot be replayed
  to get uncounted calls. (A retry after a failure uses a fresh key.)
- `DISABLE_FREE_PROXY=true` switches the route off; the database has its own switch and a global daily budget.
"""
from __future__ import annotations

import logging
import re
import time
from collections import defaultdict, deque
from typing import Any, Protocol
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from driftwatch_llm.core.judge import JUDGE_SYSTEM, build_prompt
from driftwatch_llm.core.judge import parse_score as _parse_score

logger = logging.getLogger("driftwatch.free_proxy")

MAX_TEXT_CHARS = 4000
MAX_BODY_BYTES = 8 * 1024
KEY_PATTERN = re.compile(r"^dw_[0-9a-f]{10}_[0-9a-f]{64}$")

class JudgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)
    idempotency_key: UUID


class QuotaError(Exception):
    """The database refused: `status` is the HTTP status to answer with, `detail` a fixed sentence."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


class QuotaClient(Protocol):
    def reserve(self, api_key: str, idempotency_key: str) -> dict[str, Any]: ...
    def settle(self, api_key: str, idempotency_key: str, outcome: str) -> dict[str, Any]: ...


class Provider(Protocol):
    def complete(self, system: str, prompt: str) -> str: ...


class ProviderError(Exception):
    """Any failure to get an answer from the provider. Carries no provider text."""


_REFUSALS = {
    "PT401": (401, "The project key was not accepted."),
    "PT403": (403, "Verify your email address to use the free allowance."),
    "PT429": (429, "The free allowance is used. Add your own key to keep going."),
    "PT503": (503, "The free allowance is not available right now."),
}


class SupabaseQuota:
    """reserve_quota / settle_quota through PostgREST with the public key (no service key anywhere)."""

    def __init__(self, base_url: str, anon_key: str, relay_secret: str = "", transport: httpx.BaseTransport | None = None) -> None:
        self._relay_secret = relay_secret  # proves to the database that this is the relay, not a client holding a project key
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"apikey": anon_key, "content-type": "application/json"},
            timeout=10.0,
            transport=transport,
        )

    def _call(self, fn: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            r = self._client.post(f"/rest/v1/rpc/{fn}", json=body)
        except httpx.HTTPError:
            raise QuotaError(503, "The free allowance is not available right now.") from None
        if r.status_code >= 400:
            try:
                code = r.json().get("code")
            except ValueError:
                code = None
            status, detail = _REFUSALS.get(code, (503, "The free allowance is not available right now."))
            if code == "PT422":
                status, detail = 422, "The request was not valid."
            raise QuotaError(status, detail)
        try:
            data = r.json()
        except ValueError:
            raise QuotaError(503, "The free allowance is not available right now.") from None
        return data if isinstance(data, dict) else {}

    def reserve(self, api_key: str, idempotency_key: str) -> dict[str, Any]:
        return self._call("reserve_quota", {"p_api_key": api_key, "p_idempotency_key": idempotency_key, "p_relay_secret": self._relay_secret})

    def settle(self, api_key: str, idempotency_key: str, outcome: str) -> dict[str, Any]:
        return self._call(
            "settle_quota",
            {"p_api_key": api_key, "p_idempotency_key": idempotency_key, "p_outcome": outcome, "p_relay_secret": self._relay_secret},
        )


class GroqProvider:
    """One chat completion with fixed model, `max_tokens` and temperature. The key is sent only to this URL."""

    URL = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self, api_key: str, model: str, transport: httpx.BaseTransport | None = None, timeout: float = 20.0) -> None:
        self._api_key = api_key
        self._model = model
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def complete(self, system: str, prompt: str) -> str:
        try:
            r = self._client.post(
                self.URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self._model,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                    "max_tokens": 4,
                    "temperature": 0,
                },
            )
            if r.status_code != 200:
                raise ProviderError("provider refused")
            return str(r.json()["choices"][0]["message"]["content"])
        except ProviderError:
            raise
        except Exception:  # noqa: BLE001 - timeouts, bad JSON, missing fields: all the same to the caller
            raise ProviderError("provider failed") from None


def parse_score(raw: str) -> float:
    """The judge must answer with one number from 0 to 10. Anything else (a sentence, an injected instruction) is a failure."""
    try:
        return _parse_score(raw)
    except ValueError:
        raise ProviderError("unparseable") from None


class _Windows:
    """Sliding-window counters per name (a key or an address). In memory: a restart resets them, which is fine."""

    def __init__(self, limit: int, seconds: float) -> None:
        self._limit = limit
        self._seconds = seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, name: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        q = self._hits[name]
        while q and now - q[0] > self._seconds:
            q.popleft()
        if len(q) >= self._limit:
            return False
        q.append(now)
        if len(self._hits) > 5000:  # bound memory under a flood of distinct names
            for stale in [k for k, v in self._hits.items() if not v or now - v[-1] > self._seconds][:2500]:
                self._hits.pop(stale, None)
        return True


def build_router(
    quota: QuotaClient,
    provider: Provider | None,
    disabled: bool = False,
    per_key_per_minute: int = 30,
    per_ip_per_minute: int = 60,
) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["free-allowance"])
    by_key = _Windows(per_key_per_minute, 60.0)
    by_ip = _Windows(per_ip_per_minute, 60.0)

    @router.post("/judge")
    async def judge(request: Request) -> dict[str, Any]:
        started = time.monotonic()
        status = 500
        try:
            if disabled or provider is None:
                status = 503
                raise HTTPException(503, "The free allowance is not available right now.")
            auth = request.headers.get("authorization") or ""
            key = auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else ""
            if not KEY_PATTERN.match(key):
                status = 401
                raise HTTPException(401, "The project key was not accepted.")
            forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[-1].strip()
            ip = forwarded or (request.client.host if request.client else "unknown")  # rightmost entry: added by the platform proxy
            if not by_ip.allow(ip) or not by_key.allow(key[:13]):
                status = 429
                raise HTTPException(429, "Too many requests. Try again in a minute.", headers={"Retry-After": "60"})
            declared = request.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
                status = 413
                raise HTTPException(413, "The request is too large.")
            raw = await request.body()
            if len(raw) > MAX_BODY_BYTES:
                status = 413
                raise HTTPException(413, "The request is too large.")
            try:
                body = JudgeRequest.model_validate_json(raw)
            except ValueError:
                status = 422
                raise HTTPException(422, "The request was not valid: send only text and idempotency_key.") from None

            idem = str(body.idempotency_key)
            try:
                reserved = await run_in_threadpool(quota.reserve, key, idem)
            except QuotaError as exc:
                status = exc.status
                raise HTTPException(exc.status, exc.detail) from None
            if reserved.get("replay"):
                status = 409
                raise HTTPException(409, "That request was already handled. Use a new idempotency key for a new attempt.")

            outcome = "failed"
            score = 0.0
            try:
                answer = await run_in_threadpool(provider.complete, JUDGE_SYSTEM, build_prompt(body.text))
                score = parse_score(answer)
                outcome = "ok"
            except ProviderError:
                outcome = "failed"
            except Exception:  # noqa: BLE001 - never let a provider surprise leak or skip the refund
                outcome = "failed"
            try:
                settled = await run_in_threadpool(quota.settle, key, idem, outcome)
            except QuotaError:
                settled = {}
            if outcome != "ok":
                status = 502
                raise HTTPException(502, "The judge could not score that response. Nothing was counted.")
            status = 200
            return {"score": score, "remaining": settled.get("remaining", reserved.get("remaining"))}
        finally:
            # Status and duration only. The text, the key and the provider's words never reach a log line.
            logger.info("judge status=%s ms=%d", status, int((time.monotonic() - started) * 1000))

    return router
