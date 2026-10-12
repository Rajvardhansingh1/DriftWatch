import asyncio
import inspect
import json
import sys
import time

import pytest

from driftwatch_llm.capture import wrappers
from tests.capture.fakes import (
    FakeAsyncCompletions,
    FakeAsyncCompletionsReturningAwaitable,
    FakeCompletions,
    anthropic_response,
    chat_response,
    genai_response,
    make_module,
)

SECRET_PROMPT = "PLEASE-DO-NOT-CAPTURE-THIS-PROMPT-7731"


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
    return table


def fake_openai(monkeypatch, sync=None):
    sync_cls = type("Completions", (FakeCompletions,), {})
    async_cls = type("AsyncCompletions", (FakeAsyncCompletionsReturningAwaitable,), {})
    make_module(monkeypatch, "openai.resources.chat.completions", Completions=sync_cls, AsyncCompletions=async_cls)
    return sync_cls, async_cls


def test_a_sync_call_returns_the_original_object_and_records_text_provider_model_and_latency(monkeypatch, versions, clean):
    sync_cls, _ = fake_openai(monkeypatch)
    result = chat_response("the answer", "gpt-served")
    obj = sync_cls(result=result)
    wrappers.patch_loaded()
    got = obj.create(messages=[{"role": "user", "content": SECRET_PROMPT}], model="gpt-asked")
    assert got is result
    (rec,) = clean
    assert rec["provider"] == "openai" and rec["text"] == "the answer"
    assert rec["model"] == "gpt-served"  # what the server actually used wins over what was asked for
    assert isinstance(rec["latency_ms"], float) and rec["latency_ms"] >= 0


def test_no_prompt_text_is_ever_in_a_record(monkeypatch, versions, clean):
    sync_cls, _ = fake_openai(monkeypatch)
    wrappers.patch_loaded()
    sync_cls().create(
        messages=[{"role": "system", "content": SECRET_PROMPT}, {"role": "user", "content": SECRET_PROMPT}],
        model="m", extra_body={"prompt": SECRET_PROMPT},
    )
    assert SECRET_PROMPT not in json.dumps(clean)
    assert set(clean[0]) == {"provider", "model", "text", "latency_ms"}


def test_patching_twice_wraps_once(monkeypatch, versions, clean):
    sync_cls, _ = fake_openai(monkeypatch)
    wrappers.patch_loaded()
    wrappers.patch_loaded()
    sync_cls().create(messages=[], model="m")
    assert len(clean) == 1


def test_an_exception_from_the_original_propagates_unchanged_and_records_nothing(monkeypatch, versions, clean):
    boom = RuntimeError("rate limited")
    sync_cls, _ = fake_openai(monkeypatch)
    wrappers.patch_loaded()
    with pytest.raises(RuntimeError) as exc:
        sync_cls(error=boom).create(messages=[], model="m")
    assert exc.value is boom and clean == []


def test_async_create_that_returns_an_awaitable_is_captured_after_the_await(monkeypatch, versions, clean):
    _, async_cls = fake_openai(monkeypatch)
    async_cls.result = chat_response("async answer")
    wrappers.patch_loaded()
    awaitable = async_cls().create(messages=[], model="m")
    assert clean == []  # nothing yet: the call has not been awaited
    got = asyncio.run(awaitable)
    assert got.choices[0].message.content == "async answer"
    assert [r["text"] for r in clean] == ["async answer"]


def test_a_real_async_def_stays_a_coroutine_function_and_is_captured(monkeypatch, versions, clean):
    cls = type("AsyncCompletions", (FakeAsyncCompletions,), {})
    cls.result = chat_response("groq async")
    make_module(monkeypatch, "groq.resources.chat.completions", AsyncCompletions=cls, Completions=type("Completions", (FakeCompletions,), {}))
    wrappers.patch_loaded()
    assert inspect.iscoroutinefunction(cls.create)
    asyncio.run(cls().create(messages=[], model="m"))
    assert [(r["provider"], r["text"]) for r in clean] == [("groq", "groq async")]


def test_an_async_exception_propagates_and_records_nothing(monkeypatch, versions, clean):
    _, async_cls = fake_openai(monkeypatch)
    async_cls.error = ValueError("bad request")
    wrappers.patch_loaded()
    with pytest.raises(ValueError, match="bad request"):
        asyncio.run(async_cls().create(messages=[], model="m"))
    assert clean == []


def test_streaming_calls_are_skipped_and_counted_and_the_stream_object_is_untouched(monkeypatch, versions, clean):
    sync_cls, _ = fake_openai(monkeypatch)
    stream = iter(["chunk"])
    wrappers.patch_loaded()
    got = sync_cls(result=stream).create(messages=[], model="m", stream=True)
    assert got is stream and clean == []
    assert wrappers.stats()["skipped_streaming"] == 1


def test_responses_api_and_anthropic_and_google_extractors(monkeypatch, versions, clean):
    resp_cls = type("Responses", (), {"create": lambda self, **kw: type("R", (), {"output_text": "from responses", "model": "gpt-r"})()})
    make_module(monkeypatch, "openai.resources.responses", Responses=resp_cls)
    msg_cls = type("Messages", (), {"create": lambda self, **kw: anthropic_response("claude says hi")})
    make_module(monkeypatch, "anthropic.resources.messages", Messages=msg_cls)
    gen_cls = type("Models", (), {"generate_content": lambda self, **kw: genai_response("gemini says hi")})
    make_module(monkeypatch, "google.genai.models", Models=gen_cls)
    legacy_cls = type("GenerativeModel", (), {"model_name": "models/gemini-legacy", "generate_content": lambda self, *a, **kw: genai_response("legacy says hi")})
    make_module(monkeypatch, "google.generativeai.generative_models", GenerativeModel=legacy_cls)
    wrappers.patch_loaded()
    resp_cls().create(input="x", model="gpt-r")
    msg_cls().create(model="claude-asked", max_tokens=5, messages=[])
    gen_cls().generate_content(model="gemini-asked", contents="x")
    legacy_cls().generate_content("x")
    got = [(r["provider"], r["model"], r["text"]) for r in clean]
    assert got == [
        ("openai", "gpt-r", "from responses"),
        ("anthropic", "claude-test", "claude says hi"),
        ("google", "gemini-asked", "gemini says hi"),
        ("google", "models/gemini-legacy", "legacy says hi"),
    ]


def test_an_unrecognised_response_never_raises_and_is_counted(monkeypatch, versions, clean):
    sync_cls, _ = fake_openai(monkeypatch)
    weird = object()
    wrappers.patch_loaded()
    assert sync_cls(result=weird).create(messages=[], model="m") is weird
    assert clean == [] and wrappers.stats()["skipped_other"] == 1


def test_a_failing_sink_is_swallowed_and_counted(monkeypatch, versions, clean):
    sync_cls, _ = fake_openai(monkeypatch)

    def bad_sink(record):
        raise RuntimeError("queue exploded")

    wrappers.set_sink(bad_sink)
    wrappers.patch_loaded()
    result = chat_response()
    assert sync_cls(result=result).create(messages=[], model="m") is result
    assert wrappers.stats()["errors"] == 1


def test_long_text_is_truncated_and_empty_text_is_skipped(monkeypatch, versions, clean):
    sync_cls, _ = fake_openai(monkeypatch)
    wrappers.patch_loaded()
    sync_cls(result=chat_response("x" * 50_000)).create(messages=[], model="m")
    sync_cls(result=chat_response("")).create(messages=[], model="m")
    sync_cls(result=chat_response(None)).create(messages=[], model="m")
    assert len(clean) == 1 and len(clean[0]["text"]) == 8000
    assert wrappers.stats()["skipped_other"] == 2


def test_an_unsupported_sdk_major_version_is_left_alone_and_reported(monkeypatch, versions, clean):
    versions["openai"] = "99.0.0"
    sync_cls, _ = fake_openai(monkeypatch)
    original = sync_cls.create
    wrappers.patch_loaded()
    assert sync_cls.create is original
    assert wrappers.sdk_status()["openai"] == {"version": "99.0.0", "status": "unsupported"}
    sync_cls().create(messages=[], model="m")
    assert clean == []


def test_supported_majors_are_the_ones_that_were_checked_against_the_real_sdks():
    by_dist = {t.dist: set(t.majors) for t in wrappers.TARGETS}
    assert by_dist["openai"] == {1, 2, 3}
    assert by_dist["anthropic"] == {0, 1}
    assert by_dist["groq"] == {0, 1}
    assert by_dist["google-genai"] == {1, 2}
    assert by_dist["google-generativeai"] == {0}


def test_sdk_status_reports_patched_versions(monkeypatch, versions, clean):
    fake_openai(monkeypatch)
    wrappers.patch_loaded()
    assert wrappers.sdk_status()["openai"] == {"version": "3.29.0", "status": "patched"}


def test_no_capture_suppresses_recording(monkeypatch, versions, clean):
    sync_cls, _ = fake_openai(monkeypatch)
    wrappers.patch_loaded()
    with wrappers.no_capture():
        sync_cls().create(messages=[], model="m")
    assert clean == []
    sync_cls().create(messages=[], model="m")
    assert len(clean) == 1


def test_the_overhead_per_call_is_tiny(monkeypatch, versions, clean):
    sync_cls, _ = fake_openai(monkeypatch)
    obj = sync_cls()
    n = 3000
    start = time.perf_counter()
    for _ in range(n):
        obj.create(messages=[], model="m")
    plain = time.perf_counter() - start
    wrappers.patch_loaded()
    start = time.perf_counter()
    for _ in range(n):
        obj.create(messages=[], model="m")
    wrapped = time.perf_counter() - start
    assert (wrapped - plain) / n < 0.002, f"{(wrapped - plain) / n * 1000:.3f} ms per call"


def test_a_module_imported_later_is_patched_right_after_its_import(monkeypatch, tmp_path, versions, clean):
    pkg = tmp_path / "dwfake_sdk"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "chat.py").write_text(
        "from types import SimpleNamespace as NS\n"
        "class Completions:\n"
        "    def create(self, **kw):\n"
        "        return NS(choices=[NS(message=NS(content='late hello'))], model='late-model')\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    versions["dwfake"] = "1.0.0"
    target = wrappers.Target("dwfake", "dwfake", "dwfake_sdk.chat", "Completions", "create", "openai", "chat", (1,))
    monkeypatch.setattr(wrappers, "TARGETS", [target])
    wrappers.install_import_hook()
    wrappers.patch_loaded()
    assert "dwfake_sdk.chat" not in sys.modules
    import dwfake_sdk.chat as chat  # noqa: PLC0415

    chat.Completions().create()
    assert [r["text"] for r in clean] == ["late hello"]
    monkeypatch.delitem(sys.modules, "dwfake_sdk.chat", raising=False)
    monkeypatch.delitem(sys.modules, "dwfake_sdk", raising=False)


def test_a_broken_target_does_not_break_the_import(monkeypatch, tmp_path, versions, clean):
    pkg = tmp_path / "dwfake2"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "chat.py").write_text("class Other:\n    pass\n")  # the class we expect is missing
    monkeypatch.syspath_prepend(str(tmp_path))
    versions["dwfake2"] = "1.0.0"
    monkeypatch.setattr(wrappers, "TARGETS", [wrappers.Target("dwfake2", "dwfake2", "dwfake2.chat", "Completions", "create", "openai", "chat", (1,))])
    wrappers.install_import_hook()
    wrappers.patch_loaded()
    import dwfake2.chat as chat  # noqa: PLC0415

    assert hasattr(chat, "Other")
    monkeypatch.delitem(sys.modules, "dwfake2.chat", raising=False)
    monkeypatch.delitem(sys.modules, "dwfake2", raising=False)
