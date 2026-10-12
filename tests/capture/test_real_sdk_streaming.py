"""Streaming through the REAL SDK packages over a mock HTTP transport (skipped where an SDK is not installed)."""

import asyncio

import pytest

from driftwatch_llm.capture import wrappers
from tests.capture.test_real_sdks import (  # noqa: F401  (fixtures and helpers)
    SECRET_PROMPT,
    SSE,
    async_client,
    captured,
    check_one,
    sync_client,
)

ANTHROPIC_SSE = (
    b'event: message_start\ndata: {"type":"message_start","message":{"id":"msg_1","type":"message","role":"assistant","model":"claude-served","content":[],"stop_reason":null,"stop_sequence":null,"usage":{"input_tokens":1,"output_tokens":0}}}\n\n'
    b'event: content_block_start\ndata: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}\n\n'
    b'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"hello "}}\n\n'
    b'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"stream"}}\n\n'
    b'event: content_block_stop\ndata: {"type":"content_block_stop","index":0}\n\n'
    b'event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"end_turn","stop_sequence":null},"usage":{"output_tokens":2}}\n\n'
    b'event: message_stop\ndata: {"type":"message_stop"}\n\n'
)
SSE_TWO_CHUNKS = SSE.replace(
    b"data: [DONE]",
    b'data: {"id":"c","object":"chat.completion.chunk","created":1,"model":"m","choices":[{"index":0,"delta":{"content":"more"},"finish_reason":null}]}\n\ndata: [DONE]',
)


def event_stream(body):
    return lambda mod: mod.Response(200, headers={"content-type": "text/event-stream"}, content=body)


def test_anthropic_streaming_collects_text_deltas_and_leaves_the_stream_usable(captured):
    anthropic = pytest.importorskip("anthropic")
    __import__("anthropic.resources.messages")
    wrappers.patch_loaded()
    client = anthropic.Anthropic(api_key="k", base_url="https://example.test", http_client=sync_client(anthropic, event_stream(ANTHROPIC_SSE)))
    stream = client.messages.create(model="asked", max_tokens=16, stream=True, messages=[{"role": "user", "content": SECRET_PROMPT}])
    assert captured == []  # nothing is recorded until the caller consumes the stream
    events = list(stream)
    assert events[0].type == "message_start" and len(events) == 7  # every event reached the caller
    check_one(captured, "anthropic", "hello stream")


@pytest.mark.parametrize("kind", ["openai", "groq"])
def test_chat_async_streaming_with_async_with(captured, kind):
    sdk = pytest.importorskip(kind)
    __import__(f"{kind}.resources.chat.completions")
    wrappers.patch_loaded()
    acls = sdk.AsyncOpenAI if kind == "openai" else sdk.AsyncGroq

    async def consume():
        client = acls(api_key="k", base_url="https://example.test/v1", http_client=async_client(sdk, event_stream(SSE)))
        async with await client.chat.completions.create(model="asked", messages=[{"role": "user", "content": SECRET_PROMPT}], stream=True) as stream:
            return [c async for c in stream]

    assert len(asyncio.run(consume())) >= 1
    check_one(captured, kind, "hi")


def test_leaving_a_real_stream_early_records_nothing(captured):
    openai = pytest.importorskip("openai")
    __import__("openai.resources.chat.completions")
    wrappers.patch_loaded()
    client = openai.OpenAI(api_key="k", base_url="https://example.test/v1", http_client=sync_client(openai, event_stream(SSE_TWO_CHUNKS)))
    stream = client.chat.completions.create(model="asked", messages=[{"role": "user", "content": "x"}], stream=True)
    for _chunk in stream:
        break  # the caller stops after the first chunk
    stream.close()
    assert captured == []  # a partial response is never recorded
    assert wrappers.stats()["skipped_partial"] == 1


def test_a_real_stream_consumed_in_full_is_recorded_once(captured):
    openai = pytest.importorskip("openai")
    __import__("openai.resources.chat.completions")
    wrappers.patch_loaded()
    client = openai.OpenAI(api_key="k", base_url="https://example.test/v1", http_client=sync_client(openai, event_stream(SSE_TWO_CHUNKS)))
    with client.chat.completions.create(model="asked", messages=[{"role": "user", "content": "x"}], stream=True) as stream:
        assert isinstance(stream, openai.Stream)  # the caller's own type checks still hold
        texts = [c.choices[0].delta.content for c in stream if c.choices]
    assert texts == ["hi", "more"]
    check_one(captured, "openai", "himore")
