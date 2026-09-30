from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful, accurate Q&A assistant. "
    "Answer concisely and only from what you know."
)
STRONG_MODEL = "openai/gpt-oss-120b"
WEAK_MODEL = "openai/gpt-oss-20b"


class LLMClient(Protocol):
    def complete(
        self, system_prompt: str, query: str, model: str, temperature: float = 0.0
    ) -> str: ...


@dataclass
class BotResponse:
    text: str
    model_id: str
    prompt_version: int
    temperature: float
    latency_ms: float
    timestamp: float


class QABot:
    """Controllable Q&A bot. Scenario state (model_id, system_prompt,
    prompt_version, distribution_shift_active) lives on the instance so
    scenarios.py can degrade/reset it without touching the monitor."""

    def __init__(
        self,
        client: LLMClient,
        model_id: str = STRONG_MODEL,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        rate_limiter=None,
    ):
        self.client = client
        self.model_id = model_id
        self.system_prompt = system_prompt
        self.prompt_version = 0
        self.distribution_shift_active = False
        self.rate_limiter = rate_limiter

    def ask(self, query: str, temperature: float = 0.0) -> BotResponse:
        if self.rate_limiter is not None:
            self.rate_limiter.consume()
        start = time.monotonic()
        text = self.client.complete(
            self.system_prompt, query, model=self.model_id, temperature=temperature
        )
        latency_ms = (time.monotonic() - start) * 1000
        return BotResponse(
            text=text,
            model_id=self.model_id,
            prompt_version=self.prompt_version,
            temperature=temperature,
            latency_ms=latency_ms,
            timestamp=time.time(),
        )
