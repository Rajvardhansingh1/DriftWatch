"""Contract tests against the REAL SDK packages, over a mock HTTP transport (no network, no keys).

Each test is skipped when its SDK is not installed. The main CI job does not install the SDKs; run these in
an environment that has them (for example `pip install openai anthropic groq google-genai` plus pytest, then
`pytest tests/capture/test_real_sdks.py --confcutdir=tests/capture`). Plan 9 adds a CI matrix for them.
"""

import asyncio
import json

import httpx
import pytest

from driftwatch_llm.capture import wrappers

SECRET_PROMPT = "REAL-SDK-PROMPT-THAT-MUST-NOT-BE-CAPTURED-5521"


@pytest.fixture(autouse=True)
def captured():
    records = []
    wrappers.reset_for_tests()
    wrappers.set_sink(records.append)
    yield records
    wrappers.reset_for_tests()


CHAT_JSON = {
    "id": "chatcmpl-1", "object": "chat.completion", "created": 1, "model": "model-served",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "hello from the real sdk"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
}
SSE = (
    b'data: {"id":"c","object":"chat.completion.chunk","created":1,"model":"m",'
    b'"choices":[{"index":0,"delta":{"content":"hi"},"finish_reason":null}]}\n\ndata: [DONE]\n\n'
)


def _http_module(sdk):
    """The HTTP library the SDK is built on: `httpx`, or the `httpx2` fork that the newest majors use."""
    import importlib

    for base in sdk.DefaultHttpxClient.__mro__:
        top = base.__module__.partition(".")[0]
        if top in ("httpx2", "httpx"):
            return importlib.import_module(top)
    return httpx


def sync_client(sdk, make_response):
    mod = _http_module(sdk)
    return sdk.DefaultHttpxClient(transport=mod.MockTransport(lambda request: make_response(mod)))


def async_client(sdk, make_response):
    mod = _http_module(sdk)
    return sdk.DefaultAsyncHttpxClient(transport=mod.MockTransport(lambda request: make_response(mod)))


def check_one(captured, provider, text):
    assert len(captured) == 1, captured
    rec = captured[0]
    assert rec["provider"] == provider and rec["text"] == text and rec["model"]
    assert SECRET_PROMPT not in json.dumps(captured)
    assert set(rec) == {"provider", "model", "text", "latency_ms"}


@pytest.mark.parametrize("kind", ["openai", "groq"])
def test_chat_completions_sync_async_and_streaming(captured, kind):
    sdk = pytest.importorskip(kind)
    __import__(f"{kind}.resources.chat.completions")
    wrappers.patch_loaded()
    assert wrappers.sdk_status()[kind]["status"] == "patched"
    cls = sdk.OpenAI if kind == "openai" else sdk.Groq
    acls = sdk.AsyncOpenAI if kind == "openai" else sdk.AsyncGroq
    messages = [{"role": "user", "content": SECRET_PROMPT}]
    ok = lambda mod: mod.Response(200, json=CHAT_JSON)  # noqa: E731

    client = cls(api_key="k", base_url="https://example.test/v1", http_client=sync_client(sdk, ok))
    out = client.chat.completions.create(model="asked", messages=messages)
    assert out.choices[0].message.content == "hello from the real sdk"  # the caller still gets the real object
    check_one(captured, kind, "hello from the real sdk")
    assert captured[0]["model"] == "model-served"
    captured.clear()

    aclient = acls(api_key="k", base_url="https://example.test/v1", http_client=async_client(sdk, ok))
    out = asyncio.run(aclient.chat.completions.create(model="asked", messages=messages))
    assert out.choices[0].message.content == "hello from the real sdk"
    check_one(captured, kind, "hello from the real sdk")
    captured.clear()

    sse = lambda mod: mod.Response(200, headers={"content-type": "text/event-stream"}, content=SSE)  # noqa: E731
    stream = cls(api_key="k", base_url="https://example.test/v1", http_client=sync_client(sdk, sse)).chat.completions.create(
        model="asked", messages=messages, stream=True
    )
    assert captured == []  # nothing recorded until the caller has consumed the stream
    chunks = list(stream)
    assert len(chunks) >= 1  # the stream is intact and usable
    check_one(captured, kind, "hi")  # and the text was gathered as they consumed it


def test_openai_errors_still_raise_exactly_as_before(captured):
    openai = pytest.importorskip("openai")
    __import__("openai.resources.chat.completions")
    wrappers.patch_loaded()
    bad = lambda mod: mod.Response(401, json={"error": {"message": "bad key", "type": "invalid_request_error"}})  # noqa: E731
    client = openai.OpenAI(api_key="k", base_url="https://example.test/v1", http_client=sync_client(openai, bad), max_retries=0)
    with pytest.raises(openai.AuthenticationError):
        client.chat.completions.create(model="m", messages=[{"role": "user", "content": "x"}])
    assert captured == []


ANTHROPIC_JSON = {
    "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-served",
    "content": [{"type": "text", "text": "hello from real anthropic"}],
    "stop_reason": "end_turn", "stop_sequence": None,
    "usage": {"input_tokens": 1, "output_tokens": 1},
}


def test_anthropic_sync_and_async(captured):
    anthropic = pytest.importorskip("anthropic")
    __import__("anthropic.resources.messages")
    wrappers.patch_loaded()
    assert wrappers.sdk_status()["anthropic"]["status"] == "patched"
    ok = lambda mod: mod.Response(200, json=ANTHROPIC_JSON)  # noqa: E731
    messages = [{"role": "user", "content": SECRET_PROMPT}]
    client = anthropic.Anthropic(api_key="k", base_url="https://example.test", http_client=sync_client(anthropic, ok))
    out = client.messages.create(model="asked", max_tokens=16, messages=messages)
    assert out.content[0].text == "hello from real anthropic"
    check_one(captured, "anthropic", "hello from real anthropic")
    assert captured[0]["model"] == "claude-served"
    captured.clear()
    aclient = anthropic.AsyncAnthropic(api_key="k", base_url="https://example.test", http_client=async_client(anthropic, ok))
    out = asyncio.run(aclient.messages.create(model="asked", max_tokens=16, messages=messages))
    assert out.content[0].text == "hello from real anthropic"
    check_one(captured, "anthropic", "hello from real anthropic")


def test_google_genai_patch_resolves_on_the_real_class_and_the_text_extractor_matches_real_responses(captured, monkeypatch):
    pytest.importorskip("google.genai")
    from google.genai import models, types

    response = types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=[types.Part(text="hello from real gemini")]))]
    )
    monkeypatch.setattr(models.Models, "generate_content", lambda self, **kw: response)
    wrappers.patch_loaded()
    assert wrappers.sdk_status()["google-genai"]["status"] == "patched"
    out = models.Models.generate_content(None, model="gemini-asked", contents=SECRET_PROMPT)
    assert out is response
    check_one(captured, "google", "hello from real gemini")
    assert captured[0]["model"] == "gemini-asked"


def test_legacy_google_generativeai_patch_resolves_and_text_extractor_matches(captured, monkeypatch):
    pytest.importorskip("google.generativeai")
    from google.generativeai import generative_models, types

    assert hasattr(types.GenerateContentResponse, "text")
    fake = type("R", (), {"text": "hello from legacy gemini"})()
    monkeypatch.setattr(generative_models.GenerativeModel, "generate_content", lambda self, *a, **kw: fake)
    wrappers.patch_loaded()
    assert wrappers.sdk_status()["google-generativeai"]["status"] == "patched"
    model = generative_models.GenerativeModel("gemini-legacy")
    model.generate_content(SECRET_PROMPT)
    check_one(captured, "google", "hello from legacy gemini")
    assert captured[0]["model"].endswith("gemini-legacy")
