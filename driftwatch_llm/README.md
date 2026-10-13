# driftwatch-llm

Command-line tool and local agent for [DriftWatch](https://drift-watch-rouge.vercel.app), a drift monitor for LLM apps.

```
pip install "driftwatch-llm[agent]"
driftwatch init              # sign in through your browser and link this folder to a project
driftwatch autostart enable  # optional: watch your app's LLM calls whenever it runs from this folder
driftwatch agent warmup      # first run: wait while the model (about 90 MB) downloads
driftwatch dashboard         # your charts, on this machine
driftwatch doctor            # if nothing shows up: checks the usual causes and says how to fix each
driftwatch agent status      # what the background agent is doing
```

Without the `[agent]` extra the package is just the CLI (`init`, `login`, `logout`, `trust`, `status`,
`uninstall`). Monitoring needs the extra, because the embeddings are computed on your machine.

## What it measures

One signal on real traffic: **embedding drift**, how far recent LLM responses have moved from a baseline made of
your app's first 200 responses (`driftwatch baseline freeze` can end the baseline early, with at least 30).
It reports the drift score and a combined score computed from the signals present. It does not raise alerts
yet: the alert threshold was tuned for a five-signal mix, so it is not applied to a single signal. It tells you
that drift happened, not why.

Supported SDKs: OpenAI, Anthropic, Groq and Google GenAI (the Python packages). Streaming responses are captured
as you consume them, and recorded only if the stream ends normally (a stream you stop early, or one that errors,
records nothing). Not covered: Anthropic's `client.messages.stream()` helper (use `create(stream=True)`).

## The local dashboard

`driftwatch dashboard` opens a page served by the agent on `127.0.0.1` (this machine only). The link carries a
one-time token in the part after `#`, which a browser never sends anywhere; the page trades it for an
`HttpOnly`, `SameSite=Strict` cookie. Requests with another `Host` or `Origin` are refused and there are no CORS
headers, so no other website can read it. It shows the same charts as the website, plus whether your numbers have
synced (synced, N pending, paused or offline). Only numbers exist locally, so it shows no response text.

## What leaves your machine

- Only numbers: a drift score and a few counts, sent to your own DriftWatch project with your project key.
- The text of responses goes only to a small agent running on your machine. It is held in memory, turned into
  an embedding and dropped; it is never written to disk and never sent anywhere.
- Prompts are never read.

## Keys

`driftwatch agent rotate-key` gets a fresh project key through your browser and revokes the old one; the running
agent picks it up on its next sync. `driftwatch logout` revokes this machine's key and removes it.

## What it stores and changes

- A project key in your OS keychain (or a private file if there is none), a trust record, and
  `.driftwatch/config.toml` in your project folder (a project id, nothing else).
- With `driftwatch autostart enable`, one file in your Python environment, `driftwatch_llm_autostart.pth`. It acts
  only in folders you trusted. `driftwatch autostart disable` removes it. `driftwatch run -- python app.py`
  monitors a single run without installing anything.
- Installing the package changes nothing; only the commands above do.

MIT licensed.
