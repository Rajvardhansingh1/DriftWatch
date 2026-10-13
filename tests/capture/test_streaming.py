"""Streaming responses: the caller gets the same stream (through a transparent proxy); the text is gathered as they
consume it and recorded once, only if the stream ends normally. Nothing is read ahead, nothing is buffered for them."""

import asyncio
import json
from types import SimpleNamespace as NS

import pytest

from driftwatch_llm.capture import wrappers
from tests.capture.fakes import make_module

SECRET_PROMPT = "STREAM-PROMPT-THAT-MUST-NOT-BE-CAPTURED-4410"


@pytest.fixture(autouse=True)
def clean():
    records = []
    wrappers.reset_for_tests()
    wrappers.set_sink(records.append)
    yield records
    wrappers.reset_for_tests()


@pytest.fixture
def versions(monkeypatch):
    table = {"openai": "3.29.0", "anthropic": "1.13.0", "groq": "1.7.0", "google-genai": "2.29.0", "google-generativeai": "0.8.6"}
    monkeypatch.setattr(wrappers, "_dist_version", lambda dist: table.get(dist))


def chat_chunk(text, model="gpt-stream"):
    return NS(choices=[NS(delta=NS(content=text))], model=model)


class FakeStream:
    """Like openai.Stream: iterable, a context manager, with a response attribute and close()."""

    def __init__(self, chunks, boom_at=None):
        self.chunks = chunks
        self.boom_at = boom_at
        self.closed = False
        self.response = "the-http-response"

    def __iter__(self):
        for i, c in enumerate(self.chunks):
            if self.boom_at == i:
                raise ConnectionError("stream broke")
            yield c

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        self.closed = True


class FakeAsyncStream:
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False

    def __aiter__(self):
        async def gen():
            for c in self.chunks:
                yield c

        return gen()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        self.closed = True


def install_chat(monkeypatch, result_factory):
    class Completions:
        def create(self, **kw):
            return result_factory(**kw)

    class AsyncCompletions:
        def create(self, **kw):
            async def run():
                return result_factory(**kw)

            return run()

    make_module(monkeypatch, "openai.resources.chat.completions", Completions=Completions, AsyncCompletions=AsyncCompletions)
    wrappers.patch_loaded()
    return Completions, AsyncCompletions


def test_a_consumed_stream_is_recorded_once_with_all_its_text(monkeypatch, versions, clean):
    stream = FakeStream([chat_chunk("Hel"), chat_chunk("lo "), chat_chunk(None), chat_chunk("world"), NS(choices=[], model="gpt-stream")])
    Completions, _ = install_chat(monkeypatch, lambda **kw: stream)
    got = Completions().create(model="asked", stream=True, messages=[{"role": "user", "content": SECRET_PROMPT}])
    assert clean == []  # nothing is recorded before the caller has consumed it
    items = list(got)
    assert [i.choices[0].delta.content if i.choices else "<usage>" for i in items] == ["Hel", "lo ", None, "world", "<usage>"]
    (rec,) = clean
    assert rec["text"] == "Hello world" and rec["provider"] == "openai" and rec["model"] == "gpt-stream"
    assert isinstance(rec["latency_ms"], float)
    assert SECRET_PROMPT not in json.dumps(clean)
    list(got)  # iterating a finished proxy again must not record again
    assert len(clean) == 1


def test_the_proxy_is_transparent_attributes_context_manager_and_close(monkeypatch, versions, clean):
    stream = FakeStream([chat_chunk("a"), chat_chunk("b")])
    Completions, _ = install_chat(monkeypatch, lambda **kw: stream)
    got = Completions().create(stream=True, messages=[])
    assert got.response == "the-http-response"  # delegated
    with got as s:
        assert [c.choices[0].delta.content for c in s] == ["a", "b"]
    assert stream.closed is True
    assert clean[0]["text"] == "ab"
    assert isinstance(got, FakeStream)  # isinstance checks in the caller's code keep working


def test_leaving_a_stream_early_records_nothing_and_is_counted(monkeypatch, versions, clean):
    stream = FakeStream([chat_chunk("a"), chat_chunk("b"), chat_chunk("c")])
    Completions, _ = install_chat(monkeypatch, lambda **kw: stream)
    got = Completions().create(stream=True, messages=[])
    for chunk in got:
        break
    got.close()
    assert clean == [] and wrappers.stats()["skipped_partial"] == 1
    assert stream.closed is True


def test_an_error_in_the_middle_of_a_stream_reaches_the_caller_unchanged_and_records_nothing(monkeypatch, versions, clean):
    stream = FakeStream([chat_chunk("a"), chat_chunk("b")], boom_at=1)
    Completions, _ = install_chat(monkeypatch, lambda **kw: stream)
    got = Completions().create(stream=True, messages=[])
    with pytest.raises(ConnectionError, match="stream broke"):
        list(got)
    assert clean == []


def test_async_streams_awaited_create_and_async_with(monkeypatch, versions, clean):
    stream = FakeAsyncStream([chat_chunk("as"), chat_chunk("ync")])
    _, AsyncCompletions = install_chat(monkeypatch, lambda **kw: stream)

    async def consume():
        got = await AsyncCompletions().create(stream=True, messages=[])
        async with got as s:
            return [c.choices[0].delta.content async for c in s]

    assert asyncio.run(consume()) == ["as", "ync"]
    assert [r["text"] for r in clean] == ["async"]
    assert stream.closed is True


def test_responses_api_events_collect_only_text_deltas(monkeypatch, versions, clean):
    events = [NS(type="response.created"), NS(type="response.output_text.delta", delta="Hi "), NS(type="response.output_text.delta", delta="there"),
              NS(type="response.completed", response=NS(model="gpt-r"))]

    class Responses:
        def create(self, **kw):
            return FakeStream(events)

    make_module(monkeypatch, "openai.resources.responses", Responses=Responses)
    wrappers.patch_loaded()
    list(Responses().create(stream=True, input="x", model="gpt-r"))
    assert [(r["provider"], r["text"], r["model"]) for r in clean] == [("openai", "Hi there", "gpt-r")]


def test_anthropic_stream_events_collect_only_text_deltas(monkeypatch, versions, clean):
    events = [
        NS(type="message_start"),
        NS(type="content_block_delta", delta=NS(type="text_delta", text="Claude ")),
        NS(type="content_block_delta", delta=NS(type="input_json_delta", partial_json="{}")),
        NS(type="content_block_delta", delta=NS(type="text_delta", text="says hi")),
        NS(type="message_stop"),
    ]

    class Messages:
        def create(self, **kw):
            return FakeStream(events)

    make_module(monkeypatch, "anthropic.resources.messages", Messages=Messages)
    wrappers.patch_loaded()
    list(Messages().create(stream=True, model="claude-asked", max_tokens=5, messages=[]))
    assert [(r["provider"], r["text"], r["model"]) for r in clean] == [("anthropic", "Claude says hi", "claude-asked")]


def test_google_generate_content_stream_generator_and_the_legacy_stream_flag(monkeypatch, versions, clean):
    class Models:
        def generate_content_stream(self, **kw):
            yield NS(text="gem")
            yield NS(text="ini")

    class AsyncModels:
        async def generate_content_stream(self, **kw):
            async def gen():
                yield NS(text="async ")
                yield NS(text="gemini")

            return gen()

    make_module(monkeypatch, "google.genai.models", Models=Models, AsyncModels=AsyncModels)

    class GenerativeModel:
        model_name = "models/gemini-legacy"

        def generate_content(self, *a, **kw):
            return iter([NS(text="old "), NS(text="school")])

    make_module(monkeypatch, "google.generativeai.generative_models", GenerativeModel=GenerativeModel)
    wrappers.patch_loaded()
    assert [c.text for c in Models().generate_content_stream(model="gemini-asked", contents="x")] == ["gem", "ini"]

    async def consume():
        return [c.text async for c in await AsyncModels().generate_content_stream(model="gemini-asked", contents="x")]

    assert asyncio.run(consume()) == ["async ", "gemini"]
    list(GenerativeModel().generate_content("x", stream=True))
    got = sorted((r["text"], r["model"]) for r in clean)
    assert got == [("async gemini", "gemini-asked"), ("gemini", "gemini-asked"), ("old school", "models/gemini-legacy")]


def test_a_stream_with_no_text_records_nothing(monkeypatch, versions, clean):
    stream = FakeStream([chat_chunk(None), NS(choices=[], model="m")])
    Completions, _ = install_chat(monkeypatch, lambda **kw: stream)
    list(Completions().create(stream=True, messages=[]))
    assert clean == [] and wrappers.stats()["skipped_other"] == 1


def test_long_streams_are_truncated_and_memory_stays_bounded(monkeypatch, versions, clean):
    stream = FakeStream([chat_chunk("x" * 3000)] * 20)
    Completions, _ = install_chat(monkeypatch, lambda **kw: stream)
    got = Completions().create(stream=True, messages=[])
    list(got)
    assert len(clean[0]["text"]) == 8000
    assert sum(len(p) for p in got._parts) <= 8000 + 3000  # collection stops soon after the cap


def test_a_stream_flag_with_a_non_stream_result_is_returned_unchanged(monkeypatch, versions, clean):
    odd = NS(not_a_stream=True)
    Completions, _ = install_chat(monkeypatch, lambda **kw: odd)
    assert Completions().create(stream=True, messages=[]) is odd
    assert clean == [] and wrappers.stats()["skipped_streaming"] == 1


def test_a_chunk_shape_we_do_not_know_never_breaks_the_stream(monkeypatch, versions, clean):
    weird = [object(), 5, "str", None, chat_chunk("ok")]
    stream = FakeStream(weird)
    Completions, _ = install_chat(monkeypatch, lambda **kw: stream)
    out = list(Completions().create(stream=True, messages=[]))
    assert out == weird  # the caller sees every item, unchanged
    assert [r["text"] for r in clean] == ["ok"]


def test_a_failing_sink_is_swallowed_for_streams_too(monkeypatch, versions, clean):
    stream = FakeStream([chat_chunk("a")])
    Completions, _ = install_chat(monkeypatch, lambda **kw: stream)

    def bad(record):
        raise RuntimeError("queue exploded")

    wrappers.set_sink(bad)
    assert len(list(Completions().create(stream=True, messages=[]))) == 1
    assert wrappers.stats()["errors"] == 1


def test_no_capture_suppresses_streams(monkeypatch, versions, clean):
    stream = FakeStream([chat_chunk("a")])
    Completions, _ = install_chat(monkeypatch, lambda **kw: stream)
    with wrappers.no_capture():
        got = Completions().create(stream=True, messages=[])
        list(got)
    assert clean == [] and got is stream  # not even wrapped
