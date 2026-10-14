"""The runner's provider adapters: two allow-listed hosts, fixed request shape, errors that carry no provider text."""

import json

import httpx
import pytest

from monitor.cloud import providers
from monitor.cloud.providers import BadReply, ProviderAuthError, ProviderError, complete

KEY = "gsk_" + "k" * 40


def transport(handler):
    return httpx.MockTransport(handler)


def ok(text="Paris"):
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


@pytest.mark.parametrize(
    "provider,url",
    [("groq", "https://api.groq.com/openai/v1/chat/completions"), ("openai", "https://api.openai.com/v1/chat/completions")],
)
def test_each_provider_goes_to_its_one_fixed_url_with_a_fixed_request(provider, url):
    seen = []

    def handler(request):
        seen.append((str(request.url), request.headers["authorization"], json.loads(request.content)))
        return ok("  Paris  ")

    assert complete(provider, KEY, "some-model", "be brief", "Capital of France?", temperature=0.7, transport=transport(handler)) == "Paris"
    got_url, auth, body = seen[0]
    assert got_url == url and auth == f"Bearer {KEY}"
    assert body["model"] == "some-model" and body["temperature"] == 0.7 and body["max_tokens"] == providers.MAX_TOKENS
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert set(body) == {"model", "messages", "temperature", "max_tokens"}  # nothing else is ever sent


def test_an_unknown_provider_or_a_host_override_is_refused_before_any_request():
    called = []
    t = transport(lambda r: called.append(r) or ok())
    for bad in ("anthropic", "http://evil.example", "", "GROQ", "groq/../x"):
        with pytest.raises(ProviderError):
            complete(bad, KEY, "m", "s", "p", transport=t)
    assert called == []


def test_the_hosts_are_exactly_the_allow_list():
    assert providers.HOSTS == {"groq": "api.groq.com", "openai": "api.openai.com"}


def test_a_rejected_key_is_its_own_error_other_failures_are_generic_and_carry_no_provider_text():
    leaked = f"bad key {KEY} for org secret-org"
    for status in (401, 403):
        with pytest.raises(ProviderAuthError) as e:
            complete("groq", KEY, "m", "s", "p", transport=transport(lambda r, s=status: httpx.Response(s, json={"error": {"message": leaked}})))
        assert KEY not in str(e.value) and "secret-org" not in str(e.value)
    for handler in (
        lambda r: httpx.Response(500, json={"error": {"message": leaked}}),
        lambda r: httpx.Response(429, json={"error": {"message": leaked}}),
        lambda r: httpx.Response(404, text=leaked),
        lambda r: (_ for _ in ()).throw(httpx.ReadTimeout(leaked, request=r)),
        lambda r: (_ for _ in ()).throw(httpx.ConnectError(leaked)),
    ):
        with pytest.raises(ProviderError) as e:
            complete("openai", KEY, "m", "s", "p", transport=transport(handler))
        assert not isinstance(e.value, ProviderAuthError) and KEY not in str(e.value) and "secret-org" not in str(e.value)


def test_unusable_replies_are_a_bad_reply_not_a_crash():
    for response in (
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json={"choices": [{"message": {"content": None}}]}),
        httpx.Response(200, json={"choices": [{"message": {"content": "   "}}]}),
        httpx.Response(200, json={"unexpected": True}),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json=[1, 2]),
    ):
        with pytest.raises(BadReply):
            complete("groq", KEY, "m", "s", "p", transport=transport(lambda r, x=response: x))


def test_an_enormous_reply_is_cut_not_trusted():
    out = complete("groq", KEY, "m", "s", "p", transport=transport(lambda r: ok("x" * 100_000)))
    assert len(out) <= providers.MAX_REPLY_CHARS


def test_redirects_are_not_followed():
    def handler(request):
        return httpx.Response(302, headers={"location": "https://evil.example/steal"})

    with pytest.raises(ProviderError):
        complete("groq", KEY, "m", "s", "p", transport=transport(handler))
