"""Real LLM-backed clients implementing bot.LLMClient. Requires provider
API keys in .env (see .env.example) — never called from unit tests, which
use a fake client instead (see tests/test_demo_bot.py)."""
from __future__ import annotations

from monitor.config import settings


class GroqClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.groq_api_key
        if not self.api_key:
            raise RuntimeError("GROQ_API_KEY is not set")
        from groq import Groq

        self._client = Groq(api_key=self.api_key)

    def complete(self, system_prompt: str, query: str, model: str, temperature: float = 0.0) -> str:
        resp = self._client.chat.completions.create(
            model=model,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query},
            ],
        )
        return resp.choices[0].message.content or ""


class GeminiClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.google_api_key
        if not self.api_key:
            raise RuntimeError("GOOGLE_API_KEY is not set")
        import google.generativeai as genai

        genai.configure(api_key=self.api_key)
        self._genai = genai

    def complete(self, system_prompt: str, query: str, model: str, temperature: float = 0.0) -> str:
        # Gemini has no equivalent of Groq's weak/strong model pair, so the
        # model-downgrade scenario has no visible effect on this backend —
        # Groq is the primary provider for that scenario (get_default_client).
        gemini_model = self._genai.GenerativeModel(
            model_name="gemini-1.5-flash", system_instruction=system_prompt
        )
        resp = gemini_model.generate_content(
            query, generation_config={"temperature": temperature}
        )
        return resp.text or ""


def get_default_client():
    """Groq first (primary demo/judge provider per spec section 6),
    Gemini as backup/alternate provider."""
    if settings.groq_api_key:
        return GroqClient()
    if settings.google_api_key:
        return GeminiClient()
    raise RuntimeError(
        "No LLM provider configured — set GROQ_API_KEY or GOOGLE_API_KEY in .env"
    )
