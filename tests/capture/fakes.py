"""Fake SDK modules shaped like the real ones (verified against openai 1-3, anthropic 0-1, groq 0-1,
google-genai 1-2 and google-generativeai 0.8 on 2026-10-12), including the quirk that the async
`create` methods of openai and anthropic are plain functions that RETURN an awaitable."""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace as NS


def make_module(monkeypatch, dotted: str, **attrs):
    parts = dotted.split(".")
    parent = None
    for i in range(1, len(parts) + 1):
        name = ".".join(parts[:i])
        mod = sys.modules.get(name)
        if mod is None:
            mod = types.ModuleType(name)
            mod.__path__ = []  # behave like a package so children can hang off it
            monkeypatch.setitem(sys.modules, name, mod)
        if parent is not None:
            setattr(parent, parts[i - 1], mod)
        parent = mod
    for k, v in attrs.items():
        setattr(parent, k, v)
    return parent


def chat_response(text="hello from the model", model="gpt-test"):
    return NS(choices=[NS(message=NS(content=text))], model=model)


def anthropic_response(text="hello from claude", model="claude-test"):
    return NS(content=[NS(type="thinking", thinking="..."), NS(type="text", text=text)], model=model)


def genai_response(text="hello from gemini"):
    return NS(text=text)


class FakeCompletions:
    def __init__(self, result=None, error=None):
        self.result = result if result is not None else chat_response()
        self.error = error

    def create(self, messages=None, model=None, stream=False, **kw):
        if self.error:
            raise self.error
        return self.result


class FakeAsyncCompletionsReturningAwaitable:
    """Like openai / anthropic: not `async def`, but the call returns a coroutine."""

    result = None
    error = None

    def create(self, messages=None, model=None, stream=False, **kw):
        async def run():
            if type(self).error:
                raise type(self).error
            return type(self).result if type(self).result is not None else chat_response()

        return run()


class FakeAsyncCompletions:
    """Like groq / google: a real `async def`."""

    result = None
    error = None

    async def create(self, messages=None, model=None, stream=False, **kw):
        if type(self).error:
            raise type(self).error
        return type(self).result if type(self).result is not None else chat_response()
