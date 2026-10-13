"""A stand-in for the OpenAI SDK's chat completions, with no network and no key.

It has the same module path and call shape as the real SDK (`openai.resources.chat.completions.Completions`),
which is what the DriftWatch hook patches. `traffic.py` sets `Completions.responder` to produce the text.
"""

from types import SimpleNamespace as NS


class Completions:
    responder = None  # set by traffic.py: a function (messages) -> response text

    def create(self, *, model="fake-gpt", messages=None, stream=False, **kwargs):
        text = type(self).responder(messages) if type(self).responder else "a default fake answer"
        return NS(choices=[NS(message=NS(content=text))], model=model)


class AsyncCompletions:
    """Like the real SDK: not an `async def`, but the call returns an awaitable."""

    responder = None

    def create(self, *, model="fake-gpt", messages=None, stream=False, **kwargs):
        async def run():
            text = type(self).responder(messages) if type(self).responder else "a default fake answer"
            return NS(choices=[NS(message=NS(content=text))], model=model)

        return run()
