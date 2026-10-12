"""Wrappers around the call methods of the OpenAI, Anthropic, Groq and Google GenAI SDKs.

Rules this module lives by:

1. The user's call comes first. The wrapper calls the original method and returns its result, or lets its
   exception through untouched. Recording happens after, and every step of it is inside try/except.
2. Only the response text, provider, model and latency are recorded. Prompts are never read.
3. A streaming call returns a transparent proxy of the stream. The text is gathered as the caller consumes it
   (nothing is read ahead or buffered for them) and recorded once, only if the stream ends normally; a stream
   left early or broken by an error records nothing. Unrecognised or empty responses are skipped and counted.
4. Only SDK major versions that were checked against the real packages are patched; others are left alone and
   reported as `unsupported` (checked 2026-10-12: openai 1-3, anthropic 0-1, groq 0-1, google-genai 1-2,
   google-generativeai 0.x).
5. Standard library only, and cheap to import: this module is loaded by the autostart hook.
"""

from __future__ import annotations

import contextlib
import contextvars
import functools
import sys
import threading
import time
from collections import namedtuple
from typing import Any, Callable

MAX_TEXT_CHARS = 8000

Target = namedtuple("Target", "name dist module cls method provider extractor majors streaming", defaults=(False,))

_OPENAI = ("openai", "openai", None, None, None, "openai", None, (1, 2, 3))


def _t(base, module, cls, method, extractor, streaming=False):
    return Target(base[0], base[1], module, cls, method, base[5], extractor, base[7], streaming)


_CHAT = "openai.resources.chat.completions"
_GROQ = ("groq", "groq", None, None, None, "groq", None, (0, 1))
_ANTHROPIC = ("anthropic", "anthropic", None, None, None, "anthropic", None, (0, 1))
_GENAI = ("google-genai", "google-genai", None, None, None, "google", None, (1, 2))
_LEGACY = ("google-generativeai", "google-generativeai", None, None, None, "google", None, (0,))

TARGETS = [
    _t(_OPENAI, _CHAT, "Completions", "create", "chat"),
    _t(_OPENAI, _CHAT, "AsyncCompletions", "create", "chat"),
    _t(_OPENAI, _CHAT, "Completions", "parse", "chat"),
    _t(_OPENAI, _CHAT, "AsyncCompletions", "parse", "chat"),
    _t(_OPENAI, "openai.resources.responses", "Responses", "create", "responses"),
    _t(_OPENAI, "openai.resources.responses", "AsyncResponses", "create", "responses"),
    _t(_ANTHROPIC, "anthropic.resources.messages", "Messages", "create", "anthropic"),
    _t(_ANTHROPIC, "anthropic.resources.messages", "AsyncMessages", "create", "anthropic"),
    _t(_GROQ, "groq.resources.chat.completions", "Completions", "create", "chat"),
    _t(_GROQ, "groq.resources.chat.completions", "AsyncCompletions", "create", "chat"),
    _t(_GENAI, "google.genai.models", "Models", "generate_content", "genai"),
    _t(_GENAI, "google.genai.models", "AsyncModels", "generate_content", "genai"),
    _t(_GENAI, "google.genai.models", "Models", "generate_content_stream", "genai", streaming=True),
    _t(_GENAI, "google.genai.models", "AsyncModels", "generate_content_stream", "genai", streaming=True),
    _t(_LEGACY, "google.generativeai.generative_models", "GenerativeModel", "generate_content", "genai"),
    _t(_LEGACY, "google.generativeai.generative_models", "GenerativeModel", "generate_content_async", "genai"),
]

_sink: Callable[[dict[str, Any]], None] | None = None
_suppressed: contextvars.ContextVar[bool] = contextvars.ContextVar("driftwatch_no_capture", default=False)
_stats = {"captured": 0, "skipped_streaming": 0, "skipped_partial": 0, "skipped_other": 0, "errors": 0}
_sdk: dict[str, dict[str, str]] = {}
_patched: list[tuple[Any, str, Any]] = []
_finder: Any = None
_watch: set[str] = set()


# -- public small API --------------------------------------------------------------------------
def set_sink(sink: Callable[[dict[str, Any]], None] | None) -> None:
    global _sink
    _sink = sink


def stats() -> dict[str, int]:
    return dict(_stats)


def sdk_status() -> dict[str, dict[str, str]]:
    return {k: dict(v) for k, v in _sdk.items()}


@contextlib.contextmanager
def no_capture():
    """Calls made inside this block are not recorded (for the agent's own judge or canary calls)."""
    token = _suppressed.set(True)
    try:
        yield
    finally:
        _suppressed.reset(token)


# -- extraction ----------------------------------------------------------------------------------
def _chat_text(result: Any) -> Any:
    return result.choices[0].message.content


def _responses_text(result: Any) -> Any:
    return result.output_text


def _anthropic_text(result: Any) -> Any:
    parts = [b.text for b in result.content if getattr(b, "type", None) == "text" and isinstance(getattr(b, "text", None), str)]
    return "".join(parts)


def _genai_text(result: Any) -> Any:
    return result.text


_EXTRACTORS: dict[str, Callable[[Any], Any]] = {
    "chat": _chat_text,
    "responses": _responses_text,
    "anthropic": _anthropic_text,
    "genai": _genai_text,
}


def _model_label(target: Target, owner: Any, kwargs: dict[str, Any], result: Any) -> str | None:
    for candidate in (getattr(result, "model", None), kwargs.get("model"), getattr(owner, "model_name", None)):
        if isinstance(candidate, str) and candidate.strip():
            return "".join(ch for ch in candidate if ch >= " " and ch != "\x7f")[:64]
    return None


def _deliver(record: dict[str, Any]) -> None:
    sink = _sink
    if sink is None:
        return
    try:
        sink(record)
        _stats["captured"] += 1
    except Exception:  # noqa: BLE001 - nor may a full or broken queue
        _stats["errors"] += 1


def _record(target: Target, owner: Any, kwargs: dict[str, Any], result: Any, started: float) -> None:
    if _suppressed.get():
        return
    try:
        text = _EXTRACTORS[target.extractor](result)
        if not isinstance(text, str) or not text.strip():
            _stats["skipped_other"] += 1
            return
        record = {
            "provider": target.provider,
            "model": _model_label(target, owner, kwargs, result),
            "text": text[:MAX_TEXT_CHARS],
            "latency_ms": round((time.perf_counter() - started) * 1000.0, 3),
        }
    except Exception:  # noqa: BLE001 - an unfamiliar response shape must never reach the caller
        _stats["skipped_other"] += 1
        return
    _deliver(record)


# -- streaming -----------------------------------------------------------------------------------
def _chunk_text(extractor: str, item: Any) -> Any:
    """The text carried by one stream item, or None. May raise on an unfamiliar shape (the caller ignores it)."""
    if extractor == "chat":  # openai / groq chat chunks
        choices = item.choices
        return choices[0].delta.content if choices else None
    if extractor == "responses":  # openai responses events
        return item.delta if item.type == "response.output_text.delta" else None
    if extractor == "anthropic":  # anthropic raw message stream events
        return item.delta.text if item.type == "content_block_delta" and item.delta.type == "text_delta" else None
    return item.text  # google: each chunk is a partial response


def _is_stream(obj: Any) -> bool:
    return not isinstance(obj, (str, bytes, dict, list, tuple)) and (hasattr(obj, "__iter__") or hasattr(obj, "__aiter__"))


class _StreamProxy:
    """Stands in for a stream object: everything is delegated, and the text is gathered on the way through."""

    def __init__(self, inner: Any, target: Target, owner: Any, kwargs: dict[str, Any], started: float) -> None:
        self._inner = inner
        self._target = target
        self._owner = owner
        self._kwargs = kwargs
        self._started = started
        self._parts: list[str] = []
        self._size = 0
        self._model: str | None = None
        self._it: Any = None
        self._ait: Any = None
        self._done = False
        self._broken = False
        self._partial_counted = False

    @property
    def __class__(self):  # type: ignore[override]
        return self._inner.__class__  # the caller's isinstance(stream, SomeSDKStream) keeps working

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def __repr__(self) -> str:
        return f"<driftwatch stream proxy for {self._inner!r}>"

    # -- gathering --------------------------------------------------------------------------
    def _collect(self, item: Any) -> None:
        try:
            text = _chunk_text(self._target.extractor, item)
            if isinstance(text, str) and text and self._size < MAX_TEXT_CHARS:
                self._parts.append(text)
                self._size += len(text)
            model = getattr(item, "model", None)
            if self._model is None and isinstance(model, str) and model:
                self._model = model
        except Exception:  # noqa: BLE001 - a chunk we do not understand is simply not collected
            pass

    def _finish(self) -> None:
        if self._done or self._broken:
            return
        self._done = True
        if _suppressed.get():
            return
        text = "".join(self._parts)
        if not text.strip():
            _stats["skipped_other"] += 1
            return
        model = self._model
        if not model:
            model = _model_label(self._target, self._owner, self._kwargs, None)
        _deliver(
            {
                "provider": self._target.provider,
                "model": model,
                "text": text[:MAX_TEXT_CHARS],
                "latency_ms": round((time.perf_counter() - self._started) * 1000.0, 3),
            }
        )

    def _note_closed(self) -> None:
        if not self._done and not self._broken and not self._partial_counted:
            self._partial_counted = True
            _stats["skipped_partial"] += 1  # left early: a partial response would distort the signal

    # -- sync -------------------------------------------------------------------------------
    def __iter__(self) -> "_StreamProxy":
        return self

    def __next__(self) -> Any:
        if self._it is None:
            self._it = iter(self._inner)
        try:
            item = next(self._it)
        except StopIteration:
            self._finish()
            raise
        except BaseException:
            self._broken = True
            raise
        self._collect(item)
        return item

    def __enter__(self) -> Any:
        entered = self._inner.__enter__()
        return self if entered is self._inner else entered

    def __exit__(self, *exc: Any) -> Any:
        try:
            return self._inner.__exit__(*exc)
        finally:
            self._note_closed()

    def close(self) -> Any:
        try:
            return self._inner.close()
        finally:
            self._note_closed()

    # -- async ------------------------------------------------------------------------------
    def __aiter__(self) -> "_StreamProxy":
        return self

    async def __anext__(self) -> Any:
        if self._ait is None:
            self._ait = self._inner.__aiter__()
        try:
            item = await self._ait.__anext__()
        except StopAsyncIteration:
            self._finish()
            raise
        except BaseException:
            self._broken = True
            raise
        self._collect(item)
        return item

    async def __aenter__(self) -> Any:
        entered = await self._inner.__aenter__()
        return self if entered is self._inner else entered

    async def __aexit__(self, *exc: Any) -> Any:
        try:
            return await self._inner.__aexit__(*exc)
        finally:
            self._note_closed()


def _handoff(target: Target, owner: Any, kwargs: dict[str, Any], result: Any, started: float) -> Any:
    """What the caller gets back: the result itself, or a recording proxy when it is a stream."""
    if _suppressed.get():
        return result
    if kwargs.get("stream") or target.streaming:
        try:
            if _is_stream(result):
                return _StreamProxy(result, target, owner, kwargs, started)
        except Exception:  # noqa: BLE001
            _stats["errors"] += 1
            return result
        _stats["skipped_streaming"] += 1  # flagged as a stream but not something we can wrap: hand it back untouched
        return result
    _record(target, owner, kwargs, result, started)
    return result


# -- wrapping ------------------------------------------------------------------------------------
async def _record_after(awaitable: Any, target: Target, owner: Any, kwargs: dict[str, Any], started: float) -> Any:
    result = await awaitable
    return _handoff(target, owner, kwargs, result, started)


def _make_wrapper(original: Callable[..., Any], target: Target) -> Callable[..., Any]:
    import inspect  # deferred: only paid when something is actually patched

    if inspect.iscoroutinefunction(original):

        @functools.wraps(original)
        async def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            started = time.perf_counter()
            result = await original(self, *args, **kwargs)
            return _handoff(target, self, kwargs, result, started)

    else:

        @functools.wraps(original)
        def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:  # type: ignore[misc]
            started = time.perf_counter()
            result = original(self, *args, **kwargs)
            if inspect.isawaitable(result):  # openai / anthropic: a plain function that returns a coroutine
                return _record_after(result, target, self, kwargs, started)
            return _handoff(target, self, kwargs, result, started)

    wrapper.__driftwatch_original__ = original  # type: ignore[attr-defined]
    return wrapper


def _dist_version(dist: str) -> str | None:
    try:
        from importlib import metadata

        return metadata.version(dist)
    except Exception:  # noqa: BLE001 - not installed, or vendored without metadata
        return None


def _major(version: str | None) -> int | None:
    if not version:
        return None
    head = version.split(".")[0]
    return int(head) if head.isdigit() else None


def _set_status(name: str, version: str | None, status: str) -> None:
    if _sdk.get(name, {}).get("status") == "patched":
        return  # never downgrade a name that has at least one patched method
    _sdk[name] = {"version": version or "", "status": status}


def _patch_target(module: Any, target: Target) -> None:
    version = _dist_version(target.dist)
    if _major(version) not in target.majors:
        _set_status(target.name, version, "unsupported" if version else "skipped")
        return
    owner = getattr(module, target.cls, None)
    original = getattr(owner, target.method, None) if owner is not None else None
    if original is None or not callable(original):
        _set_status(target.name, version, "skipped")
        return
    if getattr(original, "__driftwatch_original__", None) is not None:
        _set_status(target.name, version, "patched")
        return
    setattr(owner, target.method, _make_wrapper(original, target))
    _patched.append((owner, target.method, original))
    _set_status(target.name, version, "patched")


def _patch_module(module: Any) -> None:
    name = getattr(module, "__name__", None)
    for target in TARGETS:
        if target.module == name:
            try:
                _patch_target(module, target)
            except Exception:  # noqa: BLE001
                _stats["errors"] += 1


def patch_loaded() -> None:
    """Patch every target module that is already imported."""
    for name in {t.module for t in TARGETS}:
        module = sys.modules.get(name)
        if module is not None:
            _patch_module(module)


# -- patch SDKs imported later --------------------------------------------------------------------
class _PatchingLoader:
    def __init__(self, loader: Any) -> None:
        self._loader = loader

    def create_module(self, spec: Any) -> Any:
        return self._loader.create_module(spec)

    def exec_module(self, module: Any) -> None:
        self._loader.exec_module(module)
        try:
            _patch_module(module)
        except Exception:  # noqa: BLE001 - never break the user's import
            _stats["errors"] += 1
        finally:  # leave no trace on the module
            spec = getattr(module, "__spec__", None)
            if spec is not None:
                spec.loader = self._loader
            module.__loader__ = self._loader

    def __getattr__(self, name: str) -> Any:
        return getattr(self._loader, name)


class _Finder:
    def __init__(self) -> None:
        self._busy = threading.local()

    def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> Any:
        if fullname not in _watch:
            return None
        busy = getattr(self._busy, "names", None)
        if busy is None:
            busy = self._busy.names = set()
        if fullname in busy:
            return None
        busy.add(fullname)
        try:
            spec = None
            for finder in sys.meta_path:
                if finder is self:
                    continue
                find = getattr(finder, "find_spec", None)
                if find is None:
                    continue
                spec = find(fullname, path, target)
                if spec is not None:
                    break
        finally:
            busy.discard(fullname)
        if spec is None or spec.loader is None or not hasattr(spec.loader, "exec_module"):
            return spec
        spec.loader = _PatchingLoader(spec.loader)
        return spec


def install_import_hook() -> None:
    """Patch the target SDK modules right after they are imported, whenever that happens."""
    global _finder
    _watch.update(t.module for t in TARGETS)
    if _finder is None:
        _finder = _Finder()
        sys.meta_path.insert(0, _finder)


def reset_for_tests() -> None:
    global _finder, _sink
    for owner, method, original in reversed(_patched):
        setattr(owner, method, original)
    _patched.clear()
    _sdk.clear()
    for key in _stats:
        _stats[key] = 0
    _sink = None
    if _finder is not None:
        try:
            sys.meta_path.remove(_finder)
        except ValueError:
            pass
        _finder = None
    _watch.clear()
