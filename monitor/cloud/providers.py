"""The runner's provider adapters: one chat call to one of two allow-listed hosts.

Nothing a user types can choose where the request goes: the provider is a name looked up in a fixed table, the URL is
built here, redirects are not followed, and the key is sent only to that host. Errors are reduced to fixed sentences:
no provider text, and never the key, can leave this module.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import httpx

HOSTS = {"groq": "api.groq.com", "openai": "api.openai.com"}
_PATHS = {"groq": "/openai/v1/chat/completions", "openai": "/v1/chat/completions"}
MAX_TOKENS = 256  # every probe call is bounded, so a user's cost per call is bounded
MAX_REPLY_CHARS = 2000
TIMEOUT = 40.0


class ProviderError(Exception):
    """The provider could not be reached or refused. The message is a fixed sentence."""


class ProviderAuthError(ProviderError):
    """The provider rejected the key (401/403): retrying will not help."""


class BadReply(ProviderError):
    """The provider answered, but not with usable text."""


def complete(
    provider: str,
    api_key: str,
    model: str,
    system: str,
    prompt: str,
    temperature: float = 0.0,
    transport: httpx.BaseTransport | None = None,
) -> str:
    host = HOSTS.get(provider) if isinstance(provider, str) else None
    if host is None:
        raise ProviderError("that provider is not supported")
    url = f"https://{host}{_PATHS[provider]}"
    assert urlsplit(url).hostname == host  # the one place a destination is built
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": MAX_TOKENS,
    }
    try:
        with httpx.Client(transport=transport, timeout=TIMEOUT, follow_redirects=False) as client:
            response = client.post(url, headers={"Authorization": f"Bearer {api_key}"}, json=body)
    except httpx.HTTPError:
        raise ProviderError("the provider could not be reached") from None
    if response.status_code in (401, 403):
        raise ProviderAuthError("the provider rejected the key")
    if response.status_code != 200:
        raise ProviderError("the provider did not answer")
    try:
        content = response.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise BadReply("the provider's answer could not be used") from None
    if not isinstance(content, str) or not content.strip():
        raise BadReply("the provider's answer could not be used")
    return content.strip()[:MAX_REPLY_CHARS]
